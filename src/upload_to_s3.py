"""
S3 Upload Utility for Twitter Bot

This module handles uploading content folders to S3 for storage and later retrieval.
"""

import os
import boto3
import logging
import sys
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# Load environment variables from .env
load_dotenv()

# Retrieve AWS credentials and bucket info from .env
# Use standardized names with fallbacks to maintain backward compatibility
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY"))
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME", os.getenv("BUCKET_NAME"))
BUCKET_REGION = os.getenv("AWS_REGION", os.getenv("BUCKET_REGION"))

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.getenv('MAIN_LOG_FILE', 'main.log')),
            logging.StreamHandler()
        ]
    )

# Log configuration for verification
logger.info(f"S3 Upload - Bucket: {BUCKET_NAME}, Region: {BUCKET_REGION}")
if AWS_ACCESS_KEY:
    masked_key = f"{AWS_ACCESS_KEY[:4]}...{AWS_ACCESS_KEY[-4:]}" if len(AWS_ACCESS_KEY) > 8 else "[not set]"
    logger.info(f"S3 Upload - Using AWS Access Key: {masked_key}")
else:
    logger.warning("S3 Upload - AWS Access Key not configured")

# Define the local directory that contains the subfolders
LOCAL_TEST_DATA_DIR = os.getenv("LOCAL_CONTENT_FOLDER", "local_test_data")
logger.info(f"S3 Upload - Local content directory: {LOCAL_TEST_DATA_DIR}")

# Initialize S3 client
s3_client = None

def init_s3_client():
    """
    Initialize the S3 client with error handling.
    
    Returns:
        boto3.client: Initialized S3 client or None if initialization fails
    """
    global s3_client
    
    # Basic check for required variables
    if not all([AWS_ACCESS_KEY, AWS_SECRET_ACCESS_KEY, BUCKET_NAME, BUCKET_REGION]):
        missing = []
        if not AWS_ACCESS_KEY: missing.append("AWS_ACCESS_KEY_ID")
        if not AWS_SECRET_ACCESS_KEY: missing.append("AWS_SECRET_ACCESS_KEY")
        if not BUCKET_NAME: missing.append("S3_BUCKET_NAME")
        if not BUCKET_REGION: missing.append("AWS_REGION")
        
        error_msg = f"Missing required AWS environment variables: {', '.join(missing)}"
        logger.error(error_msg)
        return None

    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=BUCKET_REGION
        )
        
        # Test S3 access by listing buckets
        response = client.list_objects_v2(
            Bucket=BUCKET_NAME,
            MaxKeys=1
        )
        
        logger.info(f"S3 client initialized successfully, connected to bucket {BUCKET_NAME}")
        return client
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        error_msg = e.response.get('Error', {}).get('Message')
        logger.error(f"S3 error: {error_code} - {error_msg}")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        return None

# Try to initialize the S3 client
s3_client = init_s3_client()

def upload_folder_to_s3(folder_path, s3_client, bucket_name, s3_prefix=""):
    """
    Recursively upload all files from the given folder_path to the specified S3 bucket.
    Files will be stored under the s3_prefix (which helps preserve folder structure).
    
    Args:
        folder_path (str): Local folder path to upload
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        s3_prefix (str): Prefix to prepend to S3 keys (default: "")
        
    Returns:
        tuple: (success, uploaded_count, error_count)
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot upload")
        return False, 0, 0
        
    success = True
    uploaded_count = 0
    error_count = 0
    
    # Log the upload operation
    folder_name = os.path.basename(folder_path)
    logger.info(f"Uploading folder {folder_name} to S3 bucket {bucket_name}/{s3_prefix}")
    
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            local_path = os.path.join(root, file)
            # Calculate the relative path with respect to the folder_path (subfolder)
            relative_path = os.path.relpath(local_path, folder_path)
            # Construct the S3 key by combining the s3_prefix with the relative path
            s3_key = os.path.join(s3_prefix, relative_path).replace("\\", "/")
            
            try:
                # Get file size for logging
                file_size = os.path.getsize(local_path) / 1024  # KB
                logger.info(f"Uploading {local_path} ({file_size:.1f} KB) to s3://{bucket_name}/{s3_key}")
                
                s3_client.upload_file(local_path, bucket_name, s3_key)
                uploaded_count += 1
                logger.info(f"Successfully uploaded {local_path} to S3")
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                error_msg = e.response.get('Error', {}).get('Message')
                logger.error(f"S3 error uploading {local_path}: {error_code} - {error_msg}")
                error_count += 1
                success = False
            except Exception as e:
                logger.error(f"Failed to upload {local_path}: {e}", exc_info=True)
                error_count += 1
                success = False
    
    # Log the results
    logger.info(f"Folder {folder_name} upload completed: {uploaded_count} files uploaded, {error_count} errors")
    
    return success, uploaded_count, error_count

def main():
    """
    Main function to upload all content folders to S3.
    Loops through all subdirectories in LOCAL_TEST_DATA_DIR and uploads each one.
    """
    if not s3_client:
        logger.error("S3 client initialization failed. Cannot proceed with uploads.")
        return
        
    folder_count = 0
    upload_count = 0
    error_count = 0
    
    # Create the local directory if it doesn't exist
    if not os.path.exists(LOCAL_TEST_DATA_DIR):
        logger.warning(f"Local directory {LOCAL_TEST_DATA_DIR} doesn't exist. Creating it.")
        os.makedirs(LOCAL_TEST_DATA_DIR, exist_ok=True)
    
    # List all entries in the LOCAL_TEST_DATA_DIR
    entries = os.listdir(LOCAL_TEST_DATA_DIR)
    logger.info(f"Found {len(entries)} entries in {LOCAL_TEST_DATA_DIR}")
    
    for entry in entries:
        folder_path = os.path.join(LOCAL_TEST_DATA_DIR, entry)
        # Check if the entry is a directory (subfolder)
        if os.path.isdir(folder_path):
            folder_count += 1
            logger.info(f"Processing folder {folder_count}/{len(entries)}: {entry}")
            
            # Use the folder name as the prefix in S3
            success, uploaded, errors = upload_folder_to_s3(
                folder_path, s3_client, BUCKET_NAME, s3_prefix=f"content/{entry}"
            )
            upload_count += uploaded
            error_count += errors
    
    logger.info(f"Upload complete. Processed {folder_count} folders, uploaded {upload_count} files with {error_count} errors.")

def test_s3_connection():
    """
    Test S3 connection without uploading any files.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    if not s3_client:
        logger.error("S3 client initialization failed. Connection test failed.")
        return False
        
    try:
        # Try to list objects in the bucket
        logger.info(f"Testing connection to S3 bucket: {BUCKET_NAME}")
        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            MaxKeys=5,
            Prefix="content/"
        )
        
        # Check if the bucket exists and we have access
        if 'Contents' in response:
            object_count = len(response['Contents'])
            logger.info(f"Connection successful. Found {object_count} objects in bucket.")
            
            # Print a few object keys for verification
            if object_count > 0:
                logger.info("Sample objects:")
                for obj in response['Contents'][:3]:  # Show up to 3 objects
                    logger.info(f"  {obj['Key']} ({obj['Size']/1024:.1f} KB)")
        else:
            logger.info(f"Connection successful. Bucket exists but no content found with prefix 'content/'")
            
        return True
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        error_msg = e.response.get('Error', {}).get('Message')
        logger.error(f"S3 connection test failed: {error_code} - {error_msg}")
        return False
    except Exception as e:
        logger.error(f"S3 connection test failed: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='S3 Upload Utility')
    parser.add_argument('--test', action='store_true', help='Test S3 connection without uploading')
    parser.add_argument('--upload', action='store_true', help='Upload content to S3')
    parser.add_argument('--folder', type=str, help='Upload a specific folder only')
    
    args = parser.parse_args()
    
    if args.test:
        success = test_s3_connection()
        sys.exit(0 if success else 1)
        
    elif args.folder:
        # Upload a specific folder
        folder_path = os.path.join(LOCAL_TEST_DATA_DIR, args.folder)
        if not os.path.isdir(folder_path):
            logger.error(f"Folder not found: {folder_path}")
            sys.exit(1)
            
        logger.info(f"Uploading single folder: {args.folder}")
        success, uploaded, errors = upload_folder_to_s3(
            folder_path, s3_client, BUCKET_NAME, s3_prefix=f"content/{args.folder}"
        )
        logger.info(f"Upload complete. Uploaded {uploaded} files with {errors} errors.")
        sys.exit(0 if success else 1)
        
    elif args.upload:
        main()
        
    else:
        parser.print_help()