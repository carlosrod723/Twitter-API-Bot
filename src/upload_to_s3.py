"""
S3 Upload Utility for Twitter Bot

This module handles uploading content folders to S3 for storage and later retrieval.
Enhanced with folder management operations including upload, rename, delete, and download.
"""

import os
import boto3
import logging
import sys
import io
import zipfile
import tempfile
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
                
                # Detect content type based on file extension for better browser handling
                content_type = None
                if local_path.lower().endswith(('.jpg', '.jpeg')):
                    content_type = 'image/jpeg'
                elif local_path.lower().endswith('.png'):
                    content_type = 'image/png'
                elif local_path.lower().endswith('.txt'):
                    content_type = 'text/plain'
                
                # Set extra arguments if content type is determined
                extra_args = {}
                if content_type:
                    extra_args['ContentType'] = content_type
                
                s3_client.upload_file(
                    local_path, 
                    bucket_name, 
                    s3_key,
                    ExtraArgs=extra_args
                )
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

def upload_files_to_s3(files, s3_client, bucket_name, s3_prefix=""):
    """
    Upload a list of file objects directly to S3.
    
    Args:
        files (list): List of file objects (e.g., from request.files)
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        s3_prefix (str): Prefix to prepend to S3 keys (default: "")
        
    Returns:
        tuple: (success, uploaded_count, error_count)
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot upload files")
        return False, 0, 0
        
    success = True
    uploaded_count = 0
    error_count = 0
    
    logger.info(f"Direct uploading {len(files)} files to S3 bucket {bucket_name}/{s3_prefix}")
    
    for file in files:
        try:
            # Get a secure filename and create the S3 key
            filename = file.filename
            s3_key = os.path.join(s3_prefix, filename).replace("\\", "/")
            
            # Detect content type based on file extension
            content_type = None
            if filename.lower().endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
            elif filename.lower().endswith('.png'):
                content_type = 'image/png'
            elif filename.lower().endswith('.txt'):
                content_type = 'text/plain'
            
            # Set extra arguments if content type is determined
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type
            
            # Upload the file directly from memory
            s3_client.upload_fileobj(
                file,
                bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            uploaded_count += 1
            logger.info(f"Successfully uploaded {filename} to S3: s3://{bucket_name}/{s3_key}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            error_msg = e.response.get('Error', {}).get('Message')
            logger.error(f"S3 error uploading {file.filename}: {error_code} - {error_msg}")
            error_count += 1
            success = False
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}", exc_info=True)
            error_count += 1
            success = False
    
    # Log the results
    logger.info(f"Direct upload completed: {uploaded_count} files uploaded, {error_count} errors")
    
    return success, uploaded_count, error_count

def delete_folder_from_s3(s3_client, bucket_name, folder_prefix):
    """
    Delete all objects in a folder from S3.
    
    Args:
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        folder_prefix (str): Folder prefix to delete
        
    Returns:
        tuple: (success, deleted_count, error_message)
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot delete folder")
        return False, 0, "S3 client not initialized"
    
    try:
        # Ensure the folder prefix ends with a slash
        if not folder_prefix.endswith('/'):
            folder_prefix += '/'
            
        logger.info(f"Listing objects in S3 with prefix: {folder_prefix}")
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=folder_prefix)
        
        if 'Contents' not in response:
            logger.warning(f"No objects found in folder {folder_prefix}")
            return True, 0, "No objects found"
            
        objects = [{'Key': obj['Key']} for obj in response['Contents']]
        object_count = len(objects)
        
        if object_count == 0:
            logger.warning(f"No objects found in folder {folder_prefix}")
            return True, 0, "No objects found"
            
        logger.info(f"Deleting {object_count} objects from bucket {bucket_name} with prefix {folder_prefix}")
        
        # Delete the objects
        s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={'Objects': objects}
        )
        
        # Check if there are more objects (pagination)
        while response.get('IsTruncated', False):
            continuation_token = response.get('NextContinuationToken')
            response = s3_client.list_objects_v2(
                Bucket=bucket_name, 
                Prefix=folder_prefix,
                ContinuationToken=continuation_token
            )
            
            if 'Contents' in response:
                objects = [{'Key': obj['Key']} for obj in response['Contents']]
                if objects:
                    additional_count = len(objects)
                    logger.info(f"Deleting additional {additional_count} objects")
                    
                    s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': objects}
                    )
                    
                    object_count += additional_count
        
        logger.info(f"Successfully deleted {object_count} objects from {folder_prefix}")
        return True, object_count, None
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        error_msg = e.response.get('Error', {}).get('Message')
        error_message = f"S3 error: {error_code} - {error_msg}"
        logger.error(error_message)
        return False, 0, error_message
    except Exception as e:
        error_message = f"Failed to delete folder {folder_prefix}: {str(e)}"
        logger.error(error_message, exc_info=True)
        return False, 0, error_message

def rename_folder_in_s3(s3_client, bucket_name, old_prefix, new_prefix):
    """
    Rename a folder in S3 by copying all objects to new keys and deleting the originals.
    
    Args:
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        old_prefix (str): Current folder prefix
        new_prefix (str): New folder prefix
        
    Returns:
        tuple: (success, renamed_count, error_message)
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot rename folder")
        return False, 0, "S3 client not initialized"
    
    # Ensure prefixes end with a slash
    if not old_prefix.endswith('/'):
        old_prefix += '/'
    if not new_prefix.endswith('/'):
        new_prefix += '/'
        
    try:
        logger.info(f"Renaming folder {old_prefix} to {new_prefix} in bucket {bucket_name}")
        
        # List all objects in the old folder
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=old_prefix)
        
        if 'Contents' not in response:
            logger.warning(f"No objects found in folder {old_prefix}")
            return True, 0, "No objects found to rename"
            
        renamed_count = 0
        
        # Process objects in batches (pagination)
        while True:
            if 'Contents' not in response:
                break
                
            for obj in response['Contents']:
                old_key = obj['Key']
                
                # Create the new key by replacing the old prefix with the new prefix
                new_key = new_prefix + old_key[len(old_prefix):]
                
                logger.info(f"Copying {old_key} to {new_key}")
                
                # Copy the object to the new key
                s3_client.copy_object(
                    Bucket=bucket_name,
                    CopySource={'Bucket': bucket_name, 'Key': old_key},
                    Key=new_key
                )
                
                # Delete the old object
                s3_client.delete_object(
                    Bucket=bucket_name,
                    Key=old_key
                )
                
                renamed_count += 1
            
            # Check if there are more objects (pagination)
            if response.get('IsTruncated', False):
                continuation_token = response.get('NextContinuationToken')
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name, 
                    Prefix=old_prefix,
                    ContinuationToken=continuation_token
                )
            else:
                break
                
        logger.info(f"Successfully renamed {renamed_count} objects from {old_prefix} to {new_prefix}")
        return True, renamed_count, None
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        error_msg = e.response.get('Error', {}).get('Message')
        error_message = f"S3 error: {error_code} - {error_msg}"
        logger.error(error_message)
        return False, 0, error_message
    except Exception as e:
        error_message = f"Failed to rename folder {old_prefix} to {new_prefix}: {str(e)}"
        logger.error(error_message, exc_info=True)
        return False, 0, error_message

def create_download_archive(s3_client, bucket_name, folder_prefix, output_path=None):
    """
    Create a ZIP archive from a folder in S3.
    
    Args:
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        folder_prefix (str): Folder prefix to download
        output_path (str, optional): Path to save the ZIP file. If None, returns the ZIP data.
        
    Returns:
        tuple: (success, bytes or path, error_message)
            If output_path is None, the second element is the ZIP file bytes.
            If output_path is provided, the second element is the path to the ZIP file.
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot create download archive")
        return False, None, "S3 client not initialized"
    
    # Ensure the folder prefix ends with a slash
    if not folder_prefix.endswith('/'):
        folder_prefix += '/'
        
    try:
        logger.info(f"Creating download archive for folder {folder_prefix} in bucket {bucket_name}")
        
        # List all objects in the folder
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=folder_prefix)
        
        if 'Contents' not in response:
            logger.warning(f"No objects found in folder {folder_prefix}")
            return False, None, "No objects found to download"
            
        # Create a BytesIO object to store the ZIP file in memory
        if output_path:
            # If output path is provided, write directly to file
            zip_buffer = zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED)
        else:
            # Otherwise, write to memory buffer
            zip_buffer_io = io.BytesIO()
            zip_buffer = zipfile.ZipFile(zip_buffer_io, 'w', zipfile.ZIP_DEFLATED)
        
        file_count = 0
        
        # Process objects in batches (pagination)
        while True:
            if 'Contents' not in response:
                break
                
            for obj in response['Contents']:
                s3_key = obj['Key']
                
                # Skip the folder object itself (often has size 0)
                if s3_key == folder_prefix:
                    continue
                    
                # Get the relative path within the folder
                relative_path = s3_key[len(folder_prefix):]
                
                if relative_path:  # Skip empty paths
                    logger.info(f"Adding {s3_key} to ZIP archive as {relative_path}")
                    
                    # Download the object to a temporary buffer
                    obj_data = io.BytesIO()
                    s3_client.download_fileobj(
                        Bucket=bucket_name,
                        Key=s3_key,
                        Fileobj=obj_data
                    )
                    
                    # Reset the buffer position to the beginning
                    obj_data.seek(0)
                    
                    # Add the file to the ZIP archive
                    zip_buffer.writestr(relative_path, obj_data.read())
                    file_count += 1
            
            # Check if there are more objects (pagination)
            if response.get('IsTruncated', False):
                continuation_token = response.get('NextContinuationToken')
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name, 
                    Prefix=folder_prefix,
                    ContinuationToken=continuation_token
                )
            else:
                break
        
        # Close the ZIP file
        zip_buffer.close()
        
        if file_count == 0:
            logger.warning(f"No files found in folder {folder_prefix}")
            return False, None, "No files found to download"
            
        logger.info(f"Successfully created ZIP archive with {file_count} files from {folder_prefix}")
        
        if output_path:
            return True, output_path, None
        else:
            # Get the ZIP file bytes from the BytesIO object
            zip_buffer_io.seek(0)
            zip_bytes = zip_buffer_io.getvalue()
            return True, zip_bytes, None
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code')
        error_msg = e.response.get('Error', {}).get('Message')
        error_message = f"S3 error: {error_code} - {error_msg}"
        logger.error(error_message)
        return False, None, error_message
    except Exception as e:
        error_message = f"Failed to create download archive for {folder_prefix}: {str(e)}"
        logger.error(error_message, exc_info=True)
        return False, None, error_message

def batch_delete_from_s3(s3_client, bucket_name, folder_prefixes):
    """
    Delete multiple folders from S3.
    
    Args:
        s3_client: Initialized boto3 S3 client
        bucket_name (str): S3 bucket name
        folder_prefixes (list): List of folder prefixes to delete
        
    Returns:
        tuple: (success, results, error_message)
            results is a dictionary mapping folder prefixes to (success, deleted_count) tuples
    """
    if not s3_client:
        logger.error("S3 client not initialized, cannot perform batch delete")
        return False, {}, "S3 client not initialized"
        
    try:
        logger.info(f"Batch deleting {len(folder_prefixes)} folders from bucket {bucket_name}")
        
        results = {}
        overall_success = True
        
        for folder_prefix in folder_prefixes:
            success, deleted_count, error = delete_folder_from_s3(s3_client, bucket_name, folder_prefix)
            results[folder_prefix] = (success, deleted_count)
            
            if not success:
                overall_success = False
                logger.error(f"Failed to delete folder {folder_prefix}: {error}")
        
        if overall_success:
            logger.info(f"Successfully completed batch deletion of {len(folder_prefixes)} folders")
        else:
            logger.warning(f"Batch deletion completed with some errors")
            
        return overall_success, results, None
        
    except Exception as e:
        error_message = f"Failed to perform batch deletion: {str(e)}"
        logger.error(error_message, exc_info=True)
        return False, {}, error_message

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
    parser.add_argument('--delete', type=str, help='Delete a folder from S3')
    parser.add_argument('--rename', nargs=2, metavar=('OLD', 'NEW'), help='Rename a folder in S3')
    parser.add_argument('--download', type=str, help='Download a folder from S3 as a ZIP archive')
    parser.add_argument('--output', type=str, help='Output path for downloaded ZIP archive')
    
    args = parser.parse_args()
    
    if args.test:
        success = test_s3_connection()
        sys.exit(0 if success else 1)
        
    elif args.folder and args.upload:
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
        # Upload all folders
        main()
        
    elif args.delete:
        # Delete a folder
        logger.info(f"Deleting folder: {args.delete}")
        success, deleted, error = delete_folder_from_s3(
            s3_client, BUCKET_NAME, f"content/{args.delete}"
        )
        logger.info(f"Deletion complete. Deleted {deleted} objects.")
        if error:
            logger.error(f"Error: {error}")
        sys.exit(0 if success else 1)
        
    elif args.rename:
        # Rename a folder
        old_prefix, new_prefix = args.rename
        logger.info(f"Renaming folder: {old_prefix} to {new_prefix}")
        success, renamed, error = rename_folder_in_s3(
            s3_client, BUCKET_NAME, f"content/{old_prefix}", f"content/{new_prefix}"
        )
        logger.info(f"Rename complete. Renamed {renamed} objects.")
        if error:
            logger.error(f"Error: {error}")
        sys.exit(0 if success else 1)
        
    elif args.download:
        # Download a folder as a ZIP archive
        output_path = args.output or f"{args.download}.zip"
        logger.info(f"Downloading folder: {args.download} to {output_path}")
        success, result, error = create_download_archive(
            s3_client, BUCKET_NAME, f"content/{args.download}", output_path
        )
        if success:
            logger.info(f"Download complete. ZIP archive saved to {result}")
        else:
            logger.error(f"Error: {error}")
        sys.exit(0 if success else 1)
        
    else:
        parser.print_help()