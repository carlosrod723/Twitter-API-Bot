"""
Content Manager for Twitter Bot

This module handles all operations related to managing comic art content for tweets,
including finding, selecting, and tracking images and their summaries from both
local folders and S3.

Key features:
- Reliable content selection with fallback mechanisms
- Robust AWS S3 integration with error handling
- Smart tracking of posted content to avoid repetition
- Local file system operations with comprehensive error handling
"""

import os
import logging
import json
import random
import time
import glob
import shutil
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
import mimetypes
import hashlib

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from dotenv import load_dotenv

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.getenv('MAIN_LOG_FILE', 'main.log')),
            logging.StreamHandler()
        ]
    )

# Load environment variables
load_dotenv()

# Log configuration settings
logger.info(f"Content Manager - Local folder: {os.getenv('LOCAL_CONTENT_FOLDER', 'local_test_data')}")
logger.info(f"Content Manager - S3 enabled: {os.getenv('ENABLE_S3', 'true').lower() in ('true', '1', 'yes')}")
logger.info(f"Content Manager - S3 bucket: {os.getenv('S3_BUCKET_NAME', os.getenv('BUCKET_NAME', 'Not configured'))}")
logger.info(f"Content Manager - Content reuse days: {os.getenv('CONTENT_REUSE_DAYS', '30')}")

# AWS retry configuration
MAX_RETRIES = int(os.getenv("AWS_MAX_RETRIES", "5"))
RETRY_MODE = os.getenv("AWS_RETRY_MODE", "standard")

# AWS credentials with fallbacks
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', os.getenv('AWS_ACCESS_KEY'))
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', os.getenv('BUCKET_REGION', 'us-east-1'))

# Lock for file operations
content_lock = threading.Lock()


class ContentManager:
    """
    Content Manager for the Twitter Bot
    
    This class handles content discovery, selection, and tracking for the
    Twitter bot, supporting both local file system and S3 storage.
    
    Attributes:
        aws_access_key (str): AWS access key ID
        aws_secret_key (str): AWS secret access key
        aws_region (str): AWS region
        s3_bucket (str): S3 bucket name
        s3_content_folder (str): Folder within the S3 bucket for content
        local_content_folder (str): Local folder for content
        downloads_folder (str): Folder for downloaded content
        posting_history (dict): History of posted content
        has_s3 (bool): Whether S3 access is configured and available
        s3_client (boto3.client): S3 client for AWS operations
        last_refresh (float): Timestamp of last content refresh
        content_cache (dict): Cache of available content
    """
    
    def __init__(self):
        """Initialize content manager with configuration from environment variables."""
        logger.info("Initializing content manager")
        
        # AWS credentials for S3 access
        self.aws_access_key = AWS_ACCESS_KEY
        self.aws_secret_key = AWS_SECRET_KEY
        self.aws_region = AWS_REGION
        
        # S3 configuration
        self.s3_bucket = os.getenv('S3_BUCKET_NAME', os.getenv('BUCKET_NAME'))
        self.s3_content_folder = os.getenv('S3_CONTENT_FOLDER', 'content')
        self.enable_s3 = os.getenv('ENABLE_S3', 'true').lower() in ('true', '1', 'yes')
        
        # Local folders with path validation
        local_content_path = os.getenv('LOCAL_CONTENT_FOLDER', 'local_test_data')
        self.local_content_folder = self._validate_path(local_content_path)
        
        downloads_path = os.getenv('DOWNLOADS_FOLDER', 'downloads')
        self.downloads_folder = self._validate_path(downloads_path)
        
        # Log validated paths
        logger.debug(f"Using local content folder: {self.local_content_folder}")
        logger.debug(f"Using downloads folder: {self.downloads_folder}")
        
        # Create download folder if it doesn't exist
        self._create_directory_if_not_exists(self.downloads_folder)
        
        # Content posting history file
        self.history_file = os.path.join(self.downloads_folder, 'posting_history.json')
        self.posting_history = self._load_posting_history()
        
        # Log history status
        logger.debug(f"Loaded posting history with {len(self.posting_history.get('posted_content', []))} posted items")
        
        # Content refresh management
        self.last_refresh = 0
        self.content_cache = {'local': [], 's3': []}
        self.refresh_interval = int(os.getenv('CONTENT_REFRESH_INTERVAL_HOURS', '24')) * 3600
        
        # Initialize S3 client if we have credentials
        self.has_s3 = False
        self.s3_client = None
        
        if self.enable_s3 and self.aws_access_key and self.aws_secret_key and self.s3_bucket:
            self._initialize_s3_client()
        else:
            reason = []
            if not self.enable_s3:
                reason.append("S3 is disabled in configuration")
            if not self.aws_access_key or not self.aws_secret_key:
                reason.append("Missing AWS credentials")
            if not self.s3_bucket:
                reason.append("Missing S3 bucket name")
                
            logger.warning(f"S3 client not initialized: {', '.join(reason)}")
        
        logger.info(f"Content manager initialized with local folder: {self.local_content_folder}")
        if self.has_s3:
            logger.info(f"S3 integration enabled with bucket: {self.s3_bucket}/{self.s3_content_folder}")
    
    def _initialize_s3_client(self) -> bool:
        """
        Initialize the S3 client with AWS credentials.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Log masked credentials for debugging
            if self.aws_access_key and len(self.aws_access_key) > 8:
                masked_key = f"{self.aws_access_key[:4]}...{self.aws_access_key[-4:]}"
                logger.debug(f"Using AWS access key: {masked_key}")
            
            # Configure retry settings
            config = boto3.session.Config(
                region_name=self.aws_region,
                retries={
                    'max_attempts': MAX_RETRIES,
                    'mode': RETRY_MODE
                }
            )
            
            # Create the S3 client
            self.s3_client = boto3.client(
                's3',
                region_name=self.aws_region,
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
                config=config
            )
            
            # Verify access by checking the specific bucket (instead of listing all buckets)
            start_time = time.time()
            response = self.s3_client.list_objects_v2(Bucket=self.s3_bucket, MaxKeys=1)
            elapsed = time.time() - start_time
            
            logger.debug(f"S3 connection test successful in {elapsed:.2f}s. Verified access to bucket '{self.s3_bucket}'")
            
            self.has_s3 = True
            logger.info("S3 client initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing S3 client: {str(e)}")
            self.has_s3 = False
            return False
    
    def _validate_path(self, path: str) -> str:
        """
        Validate and normalize a file system path.
        
        Args:
            path: The path to validate
            
        Returns:
            str: The normalized path
        """
        try:
            # Convert to absolute path if relative
            if not os.path.isabs(path):
                path = os.path.abspath(path)
            
            # Normalize path (resolve .. and such)
            path = os.path.normpath(path)
            
            return path
        except Exception as e:
            logger.error(f"Error validating path {path}: {str(e)}")
            # Return the original path if there's an error
            return path
    
    def _create_directory_if_not_exists(self, directory_path: str) -> bool:
        """
        Create a directory if it doesn't exist.
        
        Args:
            directory_path: Path to the directory to create
            
        Returns:
            bool: True if successful or already exists, False otherwise
        """
        if os.path.exists(directory_path):
            if os.path.isdir(directory_path):
                return True
            else:
                logger.error(f"Path exists but is not a directory: {directory_path}")
                return False
        
        try:
            os.makedirs(directory_path, exist_ok=True)
            logger.info(f"Created directory: {directory_path}")
            return True
        except Exception as e:
            logger.error(f"Error creating directory {directory_path}: {str(e)}")
            return False
    
    def _load_posting_history(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Load posting history from file with robust error handling.
        
        Returns:
            Dict[str, List[Dict[str, str]]]: Posting history dictionary
        """
        with content_lock:
            if os.path.exists(self.history_file):
                try:
                    with open(self.history_file, 'r') as f:
                        history = json.load(f)
                    
                    # Validate the structure
                    if not isinstance(history, dict) or 'posted_content' not in history:
                        logger.warning(f"Invalid posting history structure in {self.history_file}")
                        return {'posted_content': []}
                    
                    # Log the newest and oldest posts if any exist
                    if history.get('posted_content'):
                        try:
                            sorted_posts = sorted(
                                history['posted_content'],
                                key=lambda x: x.get('posted_at', ''),
                                reverse=True
                            )
                            
                            if sorted_posts:
                                newest = sorted_posts[0].get('posted_at', 'unknown')
                                oldest = sorted_posts[-1].get('posted_at', 'unknown')
                                logger.debug(f"Posting history: newest={newest}, oldest={oldest}")
                        except Exception as e:
                            logger.error(f"Error analyzing posting dates: {str(e)}")
                    
                    logger.debug(f"Loaded posting history with {len(history['posted_content'])} items")
                    return history
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing posting history JSON: {str(e)}")
                    
                    # Create a backup of the corrupted file
                    backup_file = f"{self.history_file}.bak.{int(time.time())}"
                    try:
                        shutil.copy2(self.history_file, backup_file)
                        logger.info(f"Created backup of corrupted history file: {backup_file}")
                    except Exception as backup_err:
                        logger.error(f"Error creating backup of history file: {str(backup_err)}")
                    
                    return {'posted_content': []}
                except Exception as e:
                    logger.error(f"Error loading posting history: {str(e)}")
                    return {'posted_content': []}
            else:
                logger.info(f"Posting history file not found, creating new one")
                return {'posted_content': []}
    
    def _save_posting_history(self) -> bool:
        """
        Save posting history to file with error handling.
        
        Returns:
            bool: True if successful, False otherwise
        """
        with content_lock:
            try:
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
                
                # Save with atomic write pattern
                temp_file = f"{self.history_file}.tmp"
                with open(temp_file, 'w') as f:
                    json.dump(self.posting_history, f, indent=2)
                
                # Rename the file (atomic operation on most filesystems)
                os.replace(temp_file, self.history_file)
                
                # Log file size for debugging
                try:
                    file_size = os.path.getsize(self.history_file)
                    logger.debug(f"Saved posting history ({file_size} bytes) to {self.history_file}")
                except:
                    logger.debug(f"Saved posting history to {self.history_file}")
                    
                return True
            except Exception as e:
                logger.error(f"Error saving posting history: {str(e)}")
                return False
    
    def get_next_content_for_posting(self) -> Optional[Dict[str, str]]:
        """
        Get the next content (image + summary) for posting.
        
        This method first checks local content, then falls back to S3 if available.
        It keeps track of what's been posted to avoid repetition.
        
        Returns:
            Optional[Dict[str, str]]: A dictionary containing content details including:
                 - id: A unique identifier for the content (folder path)
                 - image_path: Path to the image file
                 - summary: The text summary from the .txt file
                 - source: Where the content came from ('local' or 's3')
                 - folder_name: The name of the folder containing the content
                 
                 Returns None if no content is available.
        """
        logger.info("Selecting next content for posting")
        
        try:
            # First check if we have local content
            logger.debug("Checking for available local content...")
            local_content = self._get_local_content()
            if local_content:
                logger.info(f"Found local content to post: {local_content['folder_name']}")
                return local_content
            
            # If no local content or all used, check S3 (if available)
            if self.has_s3:
                logger.debug("No local content available, checking S3...")
                s3_content = self._get_s3_content()
                if s3_content:
                    logger.info(f"Found S3 content to post: {s3_content['folder_name']}")
                    return s3_content
            else:
                logger.debug("S3 not available, skipping S3 content check")
            
            # If we've posted all content, check if enough time has passed to reuse content
            reuse_days = int(os.getenv('CONTENT_REUSE_DAYS', '30'))
            if reuse_days > 0:
                logger.debug(f"Checking for reusable content (older than {reuse_days} days)...")
                reuse_cutoff = datetime.now() - timedelta(days=reuse_days)
                
                # Log the cutoff date for clarity
                logger.debug(f"Content posted before {reuse_cutoff.isoformat()} can be reused")
                
                # Check for content that's old enough to reuse
                for item in self.posting_history['posted_content']:
                    try:
                        posted_at = datetime.fromisoformat(item.get('posted_at', '2000-01-01'))
                        content_id = item.get('id')
                        
                        if posted_at < reuse_cutoff and content_id:
                            # Remove this item from posting history to allow reuse
                            self.posting_history['posted_content'].remove(item)
                            self._save_posting_history()
                            
                            logger.info(f"Reusing content posted on {posted_at.isoformat()}: {content_id}")
                            
                            # Try to get the content again
                            return self.get_next_content_for_posting()
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error parsing date in posting history: {str(e)}")
            
            # If we get here, we've used all available content
            logger.warning("All content has been posted. No new content available.")
            return None
            
        except Exception as e:
            logger.error(f"Error getting content for posting: {str(e)}")
            return None
    
    def _should_refresh_content(self) -> bool:
        """
        Check if we should refresh the content cache.
        
        Returns:
            bool: True if cache should be refreshed, False otherwise
        """
        current_time = time.time()
        if current_time - self.last_refresh > self.refresh_interval:
            logger.debug(f"Content cache needs refresh (last refresh: {self.last_refresh}, interval: {self.refresh_interval}s)")
            return True
        else:
            time_since_refresh = current_time - self.last_refresh
            time_until_next = self.refresh_interval - time_since_refresh
            logger.debug(f"Content cache still valid. {time_since_refresh:.1f}s since last refresh, {time_until_next:.1f}s until next refresh")
            return False
    
    def _get_local_content(self) -> Optional[Dict[str, str]]:
        """
        Get content from local folders.
        
        This method finds and selects content from the local file system.
        
        Returns:
            Optional[Dict[str, str]]: Content details dictionary or None if no content is available
        """
        try:
            # Refresh local content list if needed
            if self._should_refresh_content():
                self._refresh_local_content()
            
            # Get a list of folders that haven't been posted
            posted_ids = [item['id'] for item in self.posting_history['posted_content']]
            available_folders = [folder for folder in self.content_cache['local'] if folder['id'] not in posted_ids]
            
            if not available_folders:
                logger.info("All local content has been posted")
                return None
            
            # Log the number of available folders
            logger.debug(f"Found {len(available_folders)} available local content folders")
            
            # Randomly select a folder
            selected_folder = random.choice(available_folders)
            
            # Find image and text files in the folder
            folder_path = selected_folder['id']
            image_files = selected_folder['images']
            text_files = selected_folder['texts']
            
            if not image_files or not text_files:
                logger.warning(f"Folder {folder_path} does not contain both image and text files")
                # Mark this folder as "posted" to avoid selecting it again
                self.mark_content_as_posted(folder_path)
                # Try again with another folder
                return self._get_local_content()
            
            # Log the files found
            logger.debug(f"Folder {folder_path} contains {len(image_files)} images and {len(text_files)} text files")
            
            # In this structure, we typically have just one image and one text file per folder
            # Fallback to random selection if multiple files exist
            image_path = image_files[0] if len(image_files) == 1 else random.choice(image_files)
            text_path = text_files[0] if len(text_files) == 1 else random.choice(text_files)
            
            # Read the summary
            try:
                with open(text_path, 'r', encoding='utf-8') as f:
                    summary = f.read().strip()
            except UnicodeDecodeError:
                # Try with different encodings if UTF-8 fails
                try:
                    with open(text_path, 'r', encoding='latin-1') as f:
                        summary = f.read().strip()
                except Exception as e:
                    logger.error(f"Error reading text file {text_path}: {str(e)}")
                    summary = f"Image from {os.path.basename(folder_path)}"
            except Exception as e:
                logger.error(f"Error reading text file {text_path}: {str(e)}")
                summary = f"Image from {os.path.basename(folder_path)}"
            
            folder_name = os.path.basename(folder_path)
            logger.info(f"Selected local content from {folder_name}: {os.path.basename(image_path)}")
            logger.debug(f"Summary length: {len(summary)} characters")
            
            return {
                'id': folder_path,
                'image_path': image_path,
                'summary': summary,
                'source': 'local',
                'folder_name': folder_name
            }
            
        except Exception as e:
            logger.error(f"Error getting local content: {str(e)}")
            return None
    
    def _refresh_local_content(self) -> int:
        """
        Refresh the cache of local content.
        
        Returns:
            int: Number of folders found
        """
        with content_lock:
            start_time = time.time()
            logger.debug(f"Refreshing local content cache...")
            
            self.content_cache['local'] = []
            
            try:
                # Check if local content folder exists
                if not os.path.exists(self.local_content_folder):
                    logger.warning(f"Local content folder does not exist: {self.local_content_folder}")
                    return 0
                
                # Get all folders in the local content directory
                folders = [f for f in glob.glob(os.path.join(self.local_content_folder, '*')) if os.path.isdir(f)]
                
                if not folders:
                    logger.warning(f"No content folders found in: {self.local_content_folder}")
                    return 0
                
                logger.debug(f"Found {len(folders)} potential content folders")
                
                # Process each folder
                for folder_path in folders:
                    try:
                        # Find image files
                        image_files = (
                            glob.glob(os.path.join(folder_path, '*.jpg')) +
                            glob.glob(os.path.join(folder_path, '*.jpeg')) +
                            glob.glob(os.path.join(folder_path, '*.png'))
                        )
                        
                        # Find text files
                        text_files = glob.glob(os.path.join(folder_path, '*.txt'))
                        
                        # Log folder contents
                        folder_name = os.path.basename(folder_path)
                        logger.debug(f"Folder {folder_name}: {len(image_files)} images, {len(text_files)} text files")
                        
                        # Add to cache if it has both image and text files
                        if image_files and text_files:
                            self.content_cache['local'].append({
                                'id': folder_path,
                                'folder_name': os.path.basename(folder_path),
                                'images': image_files,
                                'texts': text_files
                            })
                    except Exception as e:
                        logger.error(f"Error processing folder {folder_path}: {str(e)}")
                
                self.last_refresh = time.time()
                elapsed = time.time() - start_time
                logger.info(f"Refreshed local content cache in {elapsed:.2f}s: found {len(self.content_cache['local'])} folders")
                return len(self.content_cache['local'])
                
            except Exception as e:
                logger.error(f"Error refreshing local content: {str(e)}")
                return 0
    
    def _get_s3_content(self) -> Optional[Dict[str, str]]:
        """
        Get content from S3 bucket. Downloads files to the downloads folder.
        
        Returns:
            Optional[Dict[str, str]]: Content details dictionary or None if no content is available
        """
        if not self.has_s3:
            return None
        
        try:
            # Refresh S3 content list if needed
            if self._should_refresh_content():
                self._refresh_s3_content()
            
            # Get a list of folders that haven't been posted
            posted_ids = [item['id'] for item in self.posting_history['posted_content']]
            available_folders = [folder for folder in self.content_cache['s3'] if folder['id'] not in posted_ids]
            
            if not available_folders:
                logger.info("All S3 content has been posted or no valid content found")
                return None
            
            # Log available S3 folders
            logger.debug(f"Found {len(available_folders)} available S3 content folders")
            
            # Randomly select a folder
            selected_folder = random.choice(available_folders)
            folder_id = selected_folder['id']
            folder_name = selected_folder['folder_name']
            
            # Select an image and text file
            image_keys = selected_folder['images']
            text_keys = selected_folder['texts']
            
            if not image_keys or not text_keys:
                logger.warning(f"S3 folder {folder_id} has incomplete content")
                # Mark as posted to avoid selecting again
                self.mark_content_as_posted(folder_id)
                return self._get_s3_content()
            
            # Log the files found
            logger.debug(f"S3 folder {folder_name} contains {len(image_keys)} images and {len(text_keys)} text files")
            
            # Select files
            image_key = image_keys[0] if len(image_keys) == 1 else random.choice(image_keys)
            text_key = text_keys[0] if len(text_keys) == 1 else random.choice(text_keys)
            
            # Download the files
            image_filename = os.path.basename(image_key)
            text_filename = os.path.basename(text_key)
            
            # Add a unique prefix to avoid filename collisions
            prefix = hashlib.md5(folder_id.encode()).hexdigest()[:8]
            image_local_path = os.path.join(self.downloads_folder, f"{prefix}_{image_filename}")
            text_local_path = os.path.join(self.downloads_folder, f"{prefix}_{text_filename}")
            
            # Download files with error handling
            logger.debug(f"Downloading S3 files: {image_key} and {text_key}")
            image_download_success = self._download_s3_file(image_key, image_local_path)
            text_download_success = self._download_s3_file(text_key, text_local_path)
            
            if not image_download_success or not text_download_success:
                logger.error(f"Failed to download files from S3 folder {folder_id}")
                # Mark as posted to avoid selecting again
                self.mark_content_as_posted(folder_id)
                return self._get_s3_content()
            
            # Read the summary
            try:
                with open(text_local_path, 'r', encoding='utf-8') as f:
                    summary = f.read().strip()
            except UnicodeDecodeError:
                # Try with different encodings if UTF-8 fails
                try:
                    with open(text_local_path, 'r', encoding='latin-1') as f:
                        summary = f.read().strip()
                except Exception as e:
                    logger.error(f"Error reading text file {text_local_path}: {str(e)}")
                    summary = f"Image from {folder_name}"
            except Exception as e:
                logger.error(f"Error reading text file {text_local_path}: {str(e)}")
                summary = f"Image from {folder_name}"
            
            logger.info(f"Selected S3 content from {folder_name}: {image_filename}")
            logger.debug(f"Summary length: {len(summary)} characters")
            
            return {
                'id': folder_id,
                'image_path': image_local_path,
                'summary': summary,
                'source': 's3',
                'folder_name': folder_name
            }
            
        except Exception as e:
            logger.error(f"Error getting S3 content: {str(e)}")
            return None
    
    def _download_s3_file(self, key: str, local_path: str) -> bool:
        """
        Download a file from S3 with error handling.
        
        Args:
            key: S3 object key
            local_path: Local path to save the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.has_s3:
            return False
            
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            # Download with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    start_time = time.time()
                    self.s3_client.download_file(self.s3_bucket, key, local_path)
                    elapsed = time.time() - start_time
                    
                    # Log download details
                    try:
                        file_size = os.path.getsize(local_path) / 1024  # KB
                        logger.debug(f"Downloaded S3 file: {key} to {local_path} ({file_size:.1f} KB) in {elapsed:.2f}s")
                    except:
                        logger.debug(f"Downloaded S3 file: {key} to {local_path} in {elapsed:.2f}s")
                        
                    return True
                except ClientError as e:
                    # Check for specific S3 errors
                    error_code = e.response.get('Error', {}).get('Code')
                    if error_code == 'NoSuchKey':
                        logger.error(f"S3 object not found: {key}")
                        return False
                    elif attempt < max_retries - 1:
                        logger.warning(f"S3 download error (attempt {attempt+1}/{max_retries}): {str(e)}")
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        logger.error(f"Failed to download S3 file after {max_retries} attempts: {key}")
                        return False
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"S3 download error (attempt {attempt+1}/{max_retries}): {str(e)}")
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        logger.error(f"Failed to download S3 file after {max_retries} attempts: {key}")
                        return False
        except Exception as e:
            logger.error(f"Error during S3 download: {str(e)}")
            return False
    
    def _refresh_s3_content(self) -> int:
        """
        Refresh the cache of S3 content.
        
        Returns:
            int: Number of folders found
        """
        if not self.has_s3:
            return 0
            
        with content_lock:
            start_time = time.time()
            logger.debug(f"Refreshing S3 content cache...")
            
            self.content_cache['s3'] = []
            
            try:
                # List all objects in the content folder of the S3 bucket
                paginator = self.s3_client.get_paginator('list_objects_v2')
                
                # Dictionary to group files by folder
                folders = {}
                
                # Use pagination to handle many objects
                for page in paginator.paginate(
                    Bucket=self.s3_bucket,
                    Prefix=f"{self.s3_content_folder}/"
                ):
                    if 'Contents' not in page:
                        continue
                        
                    for obj in page['Contents']:
                        key = obj['Key']
                        
                        # Skip the content folder itself
                        if key == f"{self.s3_content_folder}/" or key.endswith('/'):
                            continue
                        
                        # Extract folder name and file name
                        parts = key.split('/')
                        if len(parts) >= 2:
                            folder = '/'.join(parts[:-1])  # e.g., "content/folder1"
                            filename = parts[-1]
                            
                            if folder not in folders:
                                folders[folder] = {'images': [], 'texts': []}
                            
                            lower_filename = filename.lower()
                            if any(lower_filename.endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                                folders[folder]['images'].append(key)
                            elif lower_filename.endswith('.txt'):
                                folders[folder]['texts'].append(key)
                
                # Log the raw folders found
                logger.debug(f"Found {len(folders)} potential S3 folders")
                
                # Filter out folders with no content
                valid_folders = 0
                for folder, files in folders.items():
                    # Log folder contents
                    folder_name = folder.split('/')[-1]
                    logger.debug(f"S3 folder {folder_name}: {len(files['images'])} images, {len(files['texts'])} text files")
                    
                    if files['images'] and files['texts']:
                        self.content_cache['s3'].append({
                            'id': folder,
                            'folder_name': folder.split('/')[-1],
                            'images': files['images'],
                            'texts': files['texts']
                        })
                        valid_folders += 1
                
                self.last_refresh = time.time()
                elapsed = time.time() - start_time
                logger.info(f"Refreshed S3 content cache in {elapsed:.2f}s: found {valid_folders} valid folders")
                return valid_folders
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                error_msg = e.response.get('Error', {}).get('Message')
                logger.error(f"S3 error refreshing content: {error_code} - {error_msg}")
                return 0
            except Exception as e:
                logger.error(f"Error refreshing S3 content: {str(e)}")
                return 0
    
    def mark_content_as_posted(self, content_id: str) -> bool:
        """
        Mark content as posted to avoid reuse.
        
        Args:
            content_id: The folder path or S3 prefix used as the content ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not content_id:
            logger.error("Cannot mark content as posted: empty content ID")
            return False
            
        try:
            # Check if already marked as posted to avoid duplicates
            for item in self.posting_history['posted_content']:
                if item.get('id') == content_id:
                    logger.warning(f"Content already marked as posted: {content_id}")
                    return True
            
            # Add to posting history
            posted_at = datetime.now().isoformat()
            self.posting_history['posted_content'].append({
                'id': content_id,
                'posted_at': posted_at
            })
            
            # Save posting history
            success = self._save_posting_history()
            
            if success:
                logger.info(f"Marked content as posted: {content_id} at {posted_at}")
            else:
                logger.warning(f"Failed to save posting history after marking content as posted: {content_id}")
                
            return success
            
        except Exception as e:
            logger.error(f"Error marking content as posted: {str(e)}")
            return False
    
    def list_available_content(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        List all available content that hasn't been posted yet.
        
        Returns:
            dict: A dictionary with 'local' and 's3' keys, each containing a list of available content
        """
        result = {
            'local': [],
            's3': []
        }
        
        try:
            # Make sure content cache is up to date
            if self._should_refresh_content():
                self._refresh_local_content()
                if self.has_s3:
                    self._refresh_s3_content()
            
            # Get posted content IDs
            posted_ids = [item['id'] for item in self.posting_history['posted_content']]
            
            # Filter local content
            result['local'] = [
                {
                    'id': folder['id'],
                    'folder_name': folder['folder_name'],
                    'image_files': [os.path.basename(f) for f in folder['images']],
                    'text_files': [os.path.basename(f) for f in folder['texts']]
                }
                for folder in self.content_cache['local']
                if folder['id'] not in posted_ids
            ]
            
            # Filter S3 content
            result['s3'] = [
                {
                    'id': folder['id'],
                    'folder_name': folder['folder_name'],
                    'image_files': [os.path.basename(f) for f in folder['images']],
                    'text_files': [os.path.basename(f) for f in folder['texts']]
                }
                for folder in self.content_cache['s3']
                if folder['id'] not in posted_ids
            ]
            
            logger.info(f"Available content: {len(result['local'])} local folders, {len(result['s3'])} S3 folders")
            return result
            
        except Exception as e:
            logger.error(f"Error listing available content: {str(e)}")
            return result
    
    def reset_posting_history(self) -> bool:
        """
        Reset the posting history to allow reposting all content.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create a backup of the current history
            if os.path.exists(self.history_file):
                backup_file = f"{self.history_file}.backup.{int(time.time())}"
                try:
                    shutil.copy2(self.history_file, backup_file)
                    logger.info(f"Created backup of posting history: {backup_file}")
                except Exception as e:
                    logger.error(f"Error creating backup of posting history: {str(e)}")
            
            # Reset the history
            old_count = len(self.posting_history.get('posted_content', []))
            self.posting_history = {'posted_content': []}
            success = self._save_posting_history()
            
            if success:
                logger.info(f"Posting history has been reset (cleared {old_count} items)")
            else:
                logger.error("Failed to save reset posting history")
                
            return success
        except Exception as e:
            logger.error(f"Error resetting posting history: {str(e)}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the content manager.
        
        Returns:
            Dict[str, Any]: Status information dictionary
        """
        posted_count = len(self.posting_history.get('posted_content', []))
        
        # Refresh content if needed
        if self._should_refresh_content():
            self._refresh_local_content()
            if self.has_s3:
                self._refresh_s3_content()
        
        # Count available content
        local_available = len([
            f for f in self.content_cache['local']
            if f['id'] not in [item['id'] for item in self.posting_history.get('posted_content', [])]
        ])
        
        s3_available = len([
            f for f in self.content_cache['s3']
            if f['id'] not in [item['id'] for item in self.posting_history.get('posted_content', [])]
        ])
        
        # Get most recent post
        last_post = None
        if self.posting_history.get('posted_content'):
            try:
                # Sort by posted_at date, most recent first
                sorted_posts = sorted(
                    self.posting_history['posted_content'],
                    key=lambda x: x.get('posted_at', ''),
                    reverse=True
                )
                
                if sorted_posts:
                    last_post = sorted_posts[0]
            except Exception as e:
                logger.error(f"Error determining last post: {str(e)}")
        
        # Build status dictionary
        status = {
            'content_counts': {
                'local_total': len(self.content_cache['local']),
                'local_available': local_available,
                's3_total': len(self.content_cache['s3']),
                's3_available': s3_available,
                'posted': posted_count
            },
            'local_folder': self.local_content_folder,
            'downloads_folder': self.downloads_folder,
            's3_enabled': self.has_s3,
            's3_bucket': self.s3_bucket if self.has_s3 else None,
            's3_folder': self.s3_content_folder if self.has_s3 else None,
            'last_refresh': datetime.fromtimestamp(self.last_refresh).isoformat() if self.last_refresh else None,
            'next_refresh': datetime.fromtimestamp(self.last_refresh + self.refresh_interval).isoformat() if self.last_refresh else None,
            'last_post': last_post
        }
        
        logger.info(f"Status - Local: {local_available}/{len(self.content_cache['local'])} available, S3: {s3_available}/{len(self.content_cache['s3'])} available, Posted: {posted_count}")
        
        return status


# Example usage
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Content Manager Operations')
    parser.add_argument('--list', action='store_true', help='List available content')
    parser.add_argument('--refresh', action='store_true', help='Force refresh of content cache')
    parser.add_argument('--reset', action='store_true', help='Reset posting history')
    parser.add_argument('--status', action='store_true', help='Show status information')
    parser.add_argument('--next', action='store_true', help='Show the next content for posting')
    
    args = parser.parse_args()
    
    # Create a content manager
    content_manager = ContentManager()
    
    if args.refresh:
        print("Refreshing content cache...")
        local_count = content_manager._refresh_local_content()
        print(f"Found {local_count} local content folders")
        
        if content_manager.has_s3:
            s3_count = content_manager._refresh_s3_content()
            print(f"Found {s3_count} S3 content folders")
    
    if args.list:
        print("Listing available content...")
        available = content_manager.list_available_content()
        print(f"Available local content: {len(available['local'])} folders")
        for folder in available['local']:
            print(f"  {folder['folder_name']}: {len(folder['image_files'])} images, {len(folder['text_files'])} text files")
        
        print(f"\nAvailable S3 content: {len(available['s3'])} folders")
        for folder in available['s3']:
            print(f"  {folder['folder_name']}: {len(folder['image_files'])} images, {len(folder['text_files'])} text files")
    
    if args.reset:
        print("Resetting posting history...")
        result = content_manager.reset_posting_history()
        print(f"Result: {'Success' if result else 'Failed'}")
    
    if args.next:
        print("Getting next content for posting...")
        content = content_manager.get_next_content_for_posting()
        if content:
            print(f"Selected content:")
            print(f"  Folder: {content['folder_name']}")
            print(f"  Image: {os.path.basename(content['image_path'])}")
            print(f"  Summary: {content['summary'][:100]}...")
            print(f"  Source: {content['source']}")
        else:
            print("No content available for posting")
    
    if args.status:
        print("Content Manager Status:")
        status = content_manager.get_status()
        print(json.dumps(status, indent=2))
    
    # If no args provided, show usage
    if not any(vars(args).values()):
        parser.print_help()