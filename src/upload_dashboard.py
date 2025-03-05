import os
import boto3
from flask import Blueprint, request, redirect, flash, render_template_string, jsonify, send_file, url_for
import logging
import traceback
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from src.upload_to_s3 import (
    upload_folder_to_s3, 
    upload_files_to_s3,
    delete_folder_from_s3, 
    rename_folder_in_s3, 
    create_download_archive,
    test_s3_connection
)
import uuid
import shutil
import re
import json
import io
import tempfile
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        filename='dashboard.log',
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logger.addHandler(console)

# Load environment variables
load_dotenv()

# Create a Blueprint 
app = Blueprint('upload_dashboard', __name__)

# S3 configuration
S3_BUCKET = os.getenv("S3_BUCKET_NAME", os.getenv("BUCKET_NAME"))
S3_REGION = os.getenv("AWS_REGION", os.getenv("BUCKET_REGION"))
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY"))
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Check S3 configuration
if not all([S3_BUCKET, S3_REGION, AWS_ACCESS_KEY, AWS_SECRET_ACCESS_KEY]):
    logger.warning("Missing S3 configuration in .env file. Some features may not work.")
    has_s3_config = False
else:
    has_s3_config = True
    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=S3_REGION
        )
        # Test the connection
        test_result = test_s3_connection()
        if not test_result:
            logger.warning("S3 connection test failed. Check your credentials and bucket configuration.")
            has_s3_config = False
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        has_s3_config = False

# Constants for use in the blueprint
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "txt"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_s3_content():
    """Get a list of all content stored in S3"""
    content = []
    if not has_s3_config:
        return content
    
    try:
        # List all objects in the bucket
        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=S3_BUCKET)
        
        folders = {}
        
        # Process all pages of objects
        for page in page_iterator:
            if 'Contents' in page:
                for item in page['Contents']:
                    key = item['Key']
                    parts = key.split('/')
                    
                    # Skip empty keys or objects without folder structure
                    if len(parts) <= 1:
                        continue
                    
                    folder = parts[0]
                    filename = parts[-1]
                    
                    # Skip empty filenames (folder objects)
                    if not filename:
                        continue
                    
                    # Initialize folder entry if it doesn't exist
                    if folder not in folders:
                        folders[folder] = {
                            'image_files': [],
                            'text_files': [],
                            'last_modified': None
                        }
                    
                    # Track the most recent modification date
                    if not folders[folder]['last_modified'] or item['LastModified'] > folders[folder]['last_modified']:
                        folders[folder]['last_modified'] = item['LastModified']
                    
                    # Categorize file by type
                    if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                        folders[folder]['image_files'].append(filename)
                    elif filename.lower().endswith('.txt'):
                        folders[folder]['text_files'].append(filename)
        
        # Convert to list format
        for folder, files in folders.items():
            content.append({
                'folder': folder,
                'image_files': files['image_files'],
                'text_files': files['text_files'],
                's3_path': f"s3://{S3_BUCKET}/{folder}/",
                'last_modified': files['last_modified'],
                'timestamp': files['last_modified'].timestamp() if files['last_modified'] else 0
            })
        
        # Apply default sorting (newest first)
        content.sort(key=lambda x: x['timestamp'], reverse=True)
        
    except Exception as e:
        logger.error(f"Error getting S3 content: {e}")
        logger.error(traceback.format_exc())
    
    return content

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Comic Art Content Manager</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
      body { 
        background-color: #F5F7F8; 
        font-family: 'Segoe UI', Tahoma, sans-serif; 
      }
      .container { 
        margin-top: 40px; 
        margin-bottom: 60px;
        padding-bottom: 60px;
        flex: 1 0 auto;
      }
      .alert { 
        margin-top: 20px; 
      }
      .nav-tabs { 
        margin-bottom: 20px; 
      }
      .nav-tabs .nav-link.active {
        background-color: #40C4FF;
        color: white;
        border-color: #40C4FF;
      }
      .nav-tabs .nav-link {
        color: #37474F;
      }
      .card { 
        margin-bottom: 20px; 
        border: none;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: transform 0.3s ease;
      }
      .card:hover {
        transform: translateY(-5px);
      }
      .card-header {
        background-color: #40C4FF;
        color: white;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
      }
      #drop-area {
        border: 2px dashed #78909C;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        margin-bottom: 20px;
        transition: all 0.3s ease;
      }
      #drop-area:hover {
        border-color: #40C4FF;
      }
      #drop-area.highlight {
        background-color: #80D8FF;
        border-color: #40C4FF;
      }
      .preview-container {
        display: flex;
        flex-wrap: wrap;
        gap: 15px;
        margin-top: 20px;
      }
      .preview-item {
        position: relative;
        width: 150px;
        height: 180px;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 5px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
      }
      .preview-item:hover {
        transform: translateY(-3px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
      }
      .preview-item.valid-pair {
        border-color: #40C4FF;
        background-color: rgba(128, 216, 255, 0.1);
      }
      .preview-item img {
        max-width: 140px;
        max-height: 100px;
        object-fit: contain;
      }
      .preview-item .remove-item {
        position: absolute;
        top: 5px;
        right: 5px;
        cursor: pointer;
        background: #37474F;
        color: white;
        border-radius: 50%;
        width: 24px;
        height: 24px;
        text-align: center;
        line-height: 24px;
        transition: background-color 0.2s ease;
      }
      .preview-item .remove-item:hover {
        background: #78909C;
      }
      .content-card {
        transition: transform 0.2s;
      }
      .content-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
      }
      .truncate {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
      }
      .btn-upload {
        background-color: #40C4FF;
        border-color: #40C4FF;
        color: white;
      }
      .btn-upload:hover {
        background-color: #37474F;
        border-color: #37474F;
        color: white;
      }
      .btn-outline-s3 {
        color: #40C4FF;
        border-color: #40C4FF;
      }
      .btn-outline-s3:hover {
        background-color: #40C4FF;
        color: white;
      }
      nav {
          background-color: #37474F;
          padding: 0.5px 0 !important;
          margin: 0 !important;
      }
      footer {
          text-align: center;
          padding: 2px !important;
          background-color: #37474F;
          color: #fff;
          width: 100%;
          flex-shrink: 0;
          margin: 0 !important;
      }
      .dropdown-menu-end {
        right: 0;
        left: auto;
      }
      .modal-header.danger {
        background-color: #dc3545;
        color: white;
      }
      .modal-header.primary {
        background-color: #40C4FF;
        color: white;
      }
      .btn-danger {
        background-color: #dc3545;
        border-color: #dc3545;
      }
      .actions-menu .btn {
        color: white;
        padding: 0.25rem 0.5rem;
      }
      .actions-menu .btn:hover {
        background-color: rgba(255, 255, 255, 0.2);
        border-radius: 4px;
      }
      .folder-select-checkbox {
        position: absolute;
        top: 10px;
        left: 10px;
        z-index: 10;
      }
      .batch-actions {
        display: none;
        margin-bottom: 20px;
      }
      .sort-controls {
        margin-bottom: 20px;
      }
      .file-item {
        position: relative;
        padding: 8px;
        border-radius: 5px;
        margin-bottom: 5px;
        background: rgba(0,0,0,0.03);
      }
      .file-item:hover {
        background: rgba(0,0,0,0.05);
      }
      .date-info {
        font-size: 0.8rem;
        color: #666;
        margin-top: 5px;
      }
      /* Toggle switch for batch mode */
      .switch {
        position: relative;
        display: inline-block;
        width: 60px;
        height: 30px;
      }
      .switch input {
        opacity: 0;
        width: 0;
        height: 0;
      }
      .slider {
        position: absolute;
        cursor: pointer;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: #ccc;
        transition: .4s;
        border-radius: 34px;
      }
      .slider:before {
        position: absolute;
        content: "";
        height: 22px;
        width: 22px;
        left: 4px;
        bottom: 4px;
        background-color: white;
        transition: .4s;
        border-radius: 50%;
      }
      input:checked + .slider {
        background-color: #40C4FF;
      }
      input:focus + .slider {
        box-shadow: 0 0 1px #40C4FF;
      }
      input:checked + .slider:before {
        transform: translateX(30px);
      }
      .batch-mode-label {
        margin-left: 10px;
        font-weight: 500;
        color: #37474F;
      }
    </style>
  </head>
  <body>
    <nav class="navbar navbar-expand-lg navbar-dark" style="background-color: #37474F;">
      <div class="container">
        <a class="navbar-brand" href="#">
          <i class="fab fa-twitter me-2"></i>
          Comic Art Content Manager
        </a>
      </div>
    </nav>
    
    <div class="container">
      <div class="d-flex justify-content-between align-items-center mb-4">
        <h1 style="color: #37474F;">Comic Art Content Manager</h1>
        <a href="/" class="btn btn-primary">
          <i class="fas fa-home me-2"></i> Return to Admin Portal
        </a>
      </div>
      
      <div id="alert-container">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
      </div>
      
      <ul class="nav nav-tabs" id="myTab" role="tablist">
        <li class="nav-item" role="presentation">
          <button class="nav-link active" id="upload-tab" data-bs-toggle="tab" data-bs-target="#upload" type="button" role="tab">
            <i class="fas fa-upload me-2"></i>Upload Content
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button class="nav-link" id="s3-tab" data-bs-toggle="tab" data-bs-target="#s3" type="button" role="tab">
            <i class="fas fa-cloud me-2"></i>S3 Content
          </button>
        </li>
      </ul>

      <div class="tab-content" id="myTabContent">
        <!-- Upload Tab -->
        <div class="tab-pane fade show active" id="upload" role="tabpanel">
          <div class="card">
            <div class="card-header">
              <i class="fas fa-upload me-2"></i>
              Upload New Content
            </div>
            <div class="card-body">
              <p class="text-muted">Upload image and text file pairs for your Twitter bot. Each image must have a matching text file with the same name.</p>
              
              <div id="drop-area">
                <p><i class="fas fa-file-upload fa-2x mb-2" style="color: #78909C;"></i></p>
                <p>Drag & drop image and text files here</p>
                <p>- or -</p>
                <form id="file-form">
                  <input type="file" class="form-control" id="fileInput" name="files[]" multiple accept=".jpg,.jpeg,.png,.txt">
                  <p class="mt-2"><small class="text-muted">Select multiple files at once (jpg/png and txt)</small></p>
                </form>
              </div>
              
              <div class="row mb-3">
                <div class="col-md-12">
                  <div class="form-group">
                    <label for="folderNameInput" class="form-label">Custom Folder Name (optional)</label>
                    <input type="text" class="form-control" id="folderNameInput" 
                           placeholder="Leave blank for auto-generated name (e.g., folder8)">
                    <small class="form-text text-muted">Enter a custom name for your folder or leave blank for default naming.</small>
                  </div>
                </div>
              </div>
              
              <div id="previewContainer" class="preview-container"></div>
              
              <button id="uploadButton" class="btn btn-upload mt-3" disabled>Upload Files</button>
            </div>
          </div>
        </div>
        
        <!-- S3 Content Tab -->
        <div class="tab-pane fade" id="s3" role="tabpanel">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 style="color: #37474F;">
              <i class="fas fa-cloud me-2"></i>
              S3 Cloud Storage
            </h4>
            <div class="d-flex align-items-center">
              <label class="switch me-2">
                <input type="checkbox" id="batchModeToggle">
                <span class="slider"></span>
              </label>
              <span class="batch-mode-label">Batch Mode</span>
              <button class="btn btn-sm btn-outline-secondary ms-3" id="refreshContentBtn">
                <i class="fas fa-sync-alt me-1"></i> Refresh
              </button>
            </div>
          </div>
          <p class="text-muted">Content stored in AWS S3 that can be used by the Twitter bot.</p>
          
          <!-- Sort and filter controls -->
          <div class="row mb-3 sort-controls">
            <div class="col-md-4">
              <label class="form-label">Sort By:</label>
              <select class="form-select" id="sortBySelect">
                <option value="newest">Newest First</option>
                <option value="oldest">Oldest First</option>
                <option value="name-asc">Name (A-Z)</option>
                <option value="name-desc">Name (Z-A)</option>
                <option value="count">File Count</option>
              </select>
            </div>
            <div class="col-md-4">
              <label class="form-label">Filter:</label>
              <input type="text" class="form-control" id="filterInput" placeholder="Filter by folder name">
            </div>
          </div>
          
          <!-- Batch operation controls (hidden by default) -->
          <div class="batch-actions" id="batchActionsContainer">
            <div class="d-flex align-items-center justify-content-between">
              <div>
                <span class="me-2" id="selectedCount">0 folders selected</span>
                <button class="btn btn-sm btn-outline-primary me-2" id="selectAllBtn">
                  <i class="fas fa-check-square me-1"></i> Select All
                </button>
                <button class="btn btn-sm btn-outline-secondary" id="deselectAllBtn">
                  <i class="fas fa-square me-1"></i> Deselect All
                </button>
              </div>
              <div>
                <button class="btn btn-sm btn-danger me-2" id="deleteSelectedBtn" disabled>
                  <i class="fas fa-trash-alt me-1"></i> Delete Selected
                </button>
                <button class="btn btn-sm btn-primary" id="downloadSelectedBtn" disabled>
                  <i class="fas fa-download me-1"></i> Download Selected
                </button>
              </div>
            </div>
          </div>
          
          <div class="row" id="s3Content">
            {% if has_s3_config %}
              {% if s3_content %}
                {% for item in s3_content %}
                  <div class="col-md-4 folder-item" data-folder="{{ item.folder }}" data-timestamp="{{ item.timestamp }}">
                    <div class="card content-card">
                      <!-- Checkbox for batch operations (hidden initially) -->
                      <div class="form-check folder-select-checkbox d-none">
                        <input class="form-check-input" type="checkbox" value="{{ item.folder }}" id="folder-check-{{ loop.index }}">
                      </div>
                      
                      <div class="card-header d-flex justify-content-between align-items-center">
                        <span class="truncate" title="{{ item.folder }}">{{ item.folder }}</span>
                        <div class="actions-menu">
                          <div class="dropdown">
                            <button class="btn btn-sm" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                              <i class="fas fa-ellipsis-v"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end">
                              <li><a class="dropdown-item rename-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-edit me-2"></i>Rename
                              </a></li>
                              <li><a class="dropdown-item download-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-download me-2"></i>Download as ZIP
                              </a></li>
                              <li><hr class="dropdown-divider"></li>
                              <li><a class="dropdown-item text-danger delete-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-trash-alt me-2"></i>Delete
                              </a></li>
                            </ul>
                          </div>
                        </div>
                      </div>
                      <div class="card-body">
                        {% if item.image_files %}
                          <p><strong><i class="fas fa-image me-2" style="color: #40C4FF;"></i>Images:</strong> {{ item.image_files|length }}</p>
                          <div class="file-container">
                            {% for file in item.image_files[:3] %}
                              <div class="file-item">
                                <i class="fas fa-file-image me-1" style="color: #40C4FF;"></i> {{ file }}
                              </div>
                            {% endfor %}
                            {% if item.image_files|length > 3 %}
                              <small class="text-muted">And {{ item.image_files|length - 3 }} more...</small>
                            {% endif %}
                          </div>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-image me-2"></i>No images</p>
                        {% endif %}
                        
                        {% if item.text_files %}
                          <p><strong><i class="fas fa-file-alt me-2" style="color: #78909C;"></i>Text files:</strong> {{ item.text_files|length }}</p>
                          <div class="file-container">
                            {% for file in item.text_files[:3] %}
                              <div class="file-item">
                                <i class="fas fa-file-alt me-1" style="color: #78909C;"></i> {{ file }}
                              </div>
                            {% endfor %}
                            {% if item.text_files|length > 3 %}
                              <small class="text-muted">And {{ item.text_files|length - 3 }} more...</small>
                            {% endif %}
                          </div>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-file-alt me-2"></i>No text files</p>
                        {% endif %}
                        
                        <div class="date-info mt-2">
                          <i class="fas fa-clock me-1"></i> {{ item.last_modified.strftime('%Y-%m-%d %H:%M:%S') if item.last_modified else 'Unknown date' }}
                        </div>
                      </div>
                    </div>
                  </div>
                {% endfor %}
              {% else %}
                <div class="col-12">
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No content found in S3. Upload content using the Upload tab.
                  </div>
                </div>
              {% endif %}
            {% else %}
              <div class="col-12">
                <div class="alert alert-warning">
                  <i class="fas fa-exclamation-triangle me-2"></i>
                  S3 configuration is missing. Please check your .env file.
                </div>
              </div>
            {% endif %}
          </div>
        </div>
      </div>
    </div>

    <footer>
      <div class="container">
        <div class="row">
          <div class="col-12">
            © {{ 2025 }} Twitter Bot Dashboard | Comic Art Content Manager
          </div>
        </div>
      </div>
    </footer>
    
    <!-- Delete Confirmation Modal -->
    <div class="modal fade" id="deleteConfirmationModal" tabindex="-1" aria-labelledby="deleteConfirmationModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header danger">
            <h5 class="modal-title" id="deleteConfirmationModalLabel">
              <i class="fas fa-exclamation-triangle me-2"></i>
              Confirm Deletion
            </h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <p>Are you sure you want to delete the folder <strong id="folderNameToDelete"></strong>?</p>
            <p class="text-danger"><i class="fas fa-exclamation-circle me-2"></i>This action cannot be undone!</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-danger" id="confirmDeleteBtn">Delete</button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Batch Delete Confirmation Modal -->
    <div class="modal fade" id="batchDeleteModal" tabindex="-1" aria-labelledby="batchDeleteModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header danger">
            <h5 class="modal-title" id="batchDeleteModalLabel">
              <i class="fas fa-exclamation-triangle me-2"></i>
              Confirm Batch Deletion
            </h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <p>Are you sure you want to delete <strong id="folderCountToDelete"></strong> selected folders?</p>
            <div id="foldersToDeleteList" class="alert alert-secondary" style="max-height: 200px; overflow-y: auto;"></div>
            <p class="text-danger"><i class="fas fa-exclamation-circle me-2"></i>This action cannot be undone!</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-danger" id="confirmBatchDeleteBtn">Delete All Selected</button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Rename Folder Modal -->
    <div class="modal fade" id="renameFolderModal" tabindex="-1" aria-labelledby="renameFolderModalLabel" aria-hidden="true">
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header primary">
            <h5 class="modal-title" id="renameFolderModalLabel">
              <i class="fas fa-edit me-2"></i>
              Rename Folder
            </h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <p>Rename folder <strong id="currentFolderName"></strong>:</p>
            <div class="mb-3">
              <label for="newFolderName" class="form-label">New folder name:</label>
              <input type="text" class="form-control" id="newFolderName" required>
              <div class="invalid-feedback">
                Please enter a valid folder name (letters, numbers, underscores, and hyphens only).
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-primary" id="confirmRenameBtn">Rename</button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Loading Modal -->
    <div class="modal fade" id="loadingModal" data-bs-backdrop="static" data-bs-keyboard="false" tabindex="-1" aria-labelledby="loadingModalLabel" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-body text-center p-4">
            <div class="spinner-border text-primary mb-3" role="status" style="width: 3rem; height: 3rem;">
              <span class="visually-hidden">Loading...</span>
            </div>
            <h5 id="loadingModalLabel" class="mt-3">Processing your request...</h5>
            <p id="loadingModalMessage" class="text-muted">This may take a few moments.</p>
          </div>
        </div>
      </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // Bootstrap modal instances
      const deleteModal = new bootstrap.Modal(document.getElementById('deleteConfirmationModal'));
      const batchDeleteModal = new bootstrap.Modal(document.getElementById('batchDeleteModal'));
      const renameModal = new bootstrap.Modal(document.getElementById('renameFolderModal'));
      const loadingModal = new bootstrap.Modal(document.getElementById('loadingModal'));
      
      // Show loading overlay
      function showLoading(message = "Processing your request...") {
        document.getElementById('loadingModalMessage').textContent = message;
        loadingModal.show();
      }
      
      // Hide loading overlay
      function hideLoading() {
        loadingModal.hide();
      }
      
      // Show a notification message
      function showNotification(message, type = 'success') {
        const alertContainer = document.getElementById('alert-container');
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
        alertDiv.innerHTML = `
          <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'} me-2"></i>
          ${message}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        alertContainer.appendChild(alertDiv);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
          alertDiv.classList.remove('show');
          setTimeout(() => alertDiv.remove(), 300);
        }, 5000);
      }
      
      // Refresh content handler
      document.getElementById('refreshContentBtn').addEventListener('click', function() {
        window.location.reload();
      });
      
      // Drag and drop functionality
      const dropArea = document.getElementById('drop-area');
      const fileInput = document.getElementById('fileInput');
      const previewContainer = document.getElementById('previewContainer');
      const uploadButton = document.getElementById('uploadButton');
      const folderNameInput = document.getElementById('folderNameInput');
      
      // Prevent default drag behaviors
      ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
      });
      
      // Highlight drop area when item is dragged over it
      ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, highlight, false);
      });
      
      ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, unhighlight, false);
      });
      
      // Handle dropped files
      dropArea.addEventListener('drop', handleDrop, false);
      
      // Handle selected files from the file input
      fileInput.addEventListener('change', handleFiles, false);
      
      // Upload button event
      uploadButton.addEventListener('click', uploadFiles);
      
      function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
      }
      
      function highlight() {
        dropArea.classList.add('highlight');
      }
      
      function unhighlight() {
        dropArea.classList.remove('highlight');
      }
      
      function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles({ target: { files: files } });
      }
      
      function handleFiles(e) {
        const files = Array.from(e.target.files);
        previewContainer.innerHTML = '';
        
        // Group files by name (without extension)
        const fileGroups = {};
        files.forEach(file => {
          const nameWithoutExt = file.name.substring(0, file.name.lastIndexOf('.'));
          if (!fileGroups[nameWithoutExt]) {
            fileGroups[nameWithoutExt] = [];
          }
          fileGroups[nameWithoutExt].push(file);
        });
        
        // Check for pairs and create previews
        for (const [baseName, groupFiles] of Object.entries(fileGroups)) {
          createPreviewItem(baseName, groupFiles);
        }
        
        updateUploadButton();
      }
      
      function createPreviewItem(baseName, files) {
        const imageFile = files.find(f => /\.(jpe?g|png)$/i.test(f.name));
        const textFile = files.find(f => /\.txt$/i.test(f.name));
        
        const previewItem = document.createElement('div');
        previewItem.className = 'preview-item';
        previewItem.dataset.baseName = baseName;
        
        // Add remove button
        const removeBtn = document.createElement('div');
        removeBtn.className = 'remove-item';
        removeBtn.innerHTML = '×';
        removeBtn.addEventListener('click', () => {
          previewItem.remove();
          updateUploadButton();
        });
        previewItem.appendChild(removeBtn);
        
        // Add image preview if available
        if (imageFile) {
          const img = document.createElement('img');
          img.file = imageFile;
          previewItem.appendChild(img);
          
          const reader = new FileReader();
          reader.onload = (function(aImg) { return function(e) { aImg.src = e.target.result; }; })(img);
          reader.readAsDataURL(imageFile);
          
          previewItem.dataset.imageFile = imageFile.name;
        }
        
        // Add text file info if available
        if (textFile) {
          const textInfo = document.createElement('div');
          textInfo.className = 'mt-2';
          
          const reader = new FileReader();
          reader.onload = function(e) {
            const preview = e.target.result.substring(0, 50) + (e.target.result.length > 50 ? '...' : '');
            textInfo.innerHTML = `<small>${textFile.name}</small><br><small class="text-muted">${preview}</small>`;
          };
          reader.readAsText(textFile);
          
          previewItem.appendChild(textInfo);
          previewItem.dataset.textFile = textFile.name;
        }
        
        // Add validation class
        if (imageFile && textFile) {
          previewItem.classList.add('valid-pair');
        } else {
          const warning = document.createElement('div');
          warning.className = 'text-danger mt-1';
          warning.innerHTML = '<small>Missing ' + (imageFile ? 'text file' : 'image file') + '</small>';
          previewItem.appendChild(warning);
        }
        
        previewContainer.appendChild(previewItem);
      }
      
      function updateUploadButton() {
        // Enable upload button if there's at least one valid pair
        const validPairs = document.querySelectorAll('.valid-pair').length;
        uploadButton.disabled = validPairs === 0;
        uploadButton.innerHTML = validPairs > 0 ? 
          `<i class="fas fa-upload me-2"></i>Upload ${validPairs} File Pair${validPairs > 1 ? 's' : ''}` : 
          '<i class="fas fa-upload me-2"></i>Upload Files';
      }
      
      function uploadFiles() {
        const validPairs = document.querySelectorAll('.valid-pair');
        if (validPairs.length === 0) return;
        
        // Create FormData
        const formData = new FormData();
        
        // Add custom folder name if provided
        const customFolderName = folderNameInput.value.trim();
        if (customFolderName) {
          formData.append('folder_name', customFolderName);
        }
        
        // Add all valid pairs to the FormData
        validPairs.forEach(item => {
          // Find the file objects in the file input that match our preview items
          const imageFileName = item.dataset.imageFile;
          const textFileName = item.dataset.textFile;
          
          let imageFile, textFile;
          
          Array.from(fileInput.files).forEach(file => {
            if (file.name === imageFileName) imageFile = file;
            if (file.name === textFileName) textFile = file;
          });
          
          if (imageFile && textFile) {
            formData.append('images', imageFile);
            formData.append('texts', textFile);
          }
        });
        
        // Show loading state
        uploadButton.disabled = true;
        uploadButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Uploading...';
        showLoading("Uploading files to S3...");
        
        // Send Ajax request
        fetch('/upload/upload-files', {
          method: 'POST',
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            // Clear preview
            previewContainer.innerHTML = '';
            fileInput.value = '';
            folderNameInput.value = '';
            
            // Show success message
            showNotification(data.message, 'success');
            
            // Reset button
            uploadButton.innerHTML = '<i class="fas fa-upload me-2"></i>Upload Files';
            uploadButton.disabled = true;
            
            // Switch to S3 tab after a delay
            setTimeout(() => {
              document.getElementById('s3-tab').click();
              
              // Refresh content after switching tabs
              setTimeout(() => {
                refreshS3Content();
              }, 500);
            }, 1000);
          } else {
            // Show error
            showNotification(data.message, 'danger');
            
            // Reset button
            uploadButton.innerHTML = '<i class="fas fa-redo me-2"></i>Try Again';
            uploadButton.disabled = false;
          }
        })
        .catch(error => {
          hideLoading();
          console.error('Error:', error);
          
          // Show error
          showNotification('An error occurred during upload. Please try again.', 'danger');
          
          // Reset button
          uploadButton.innerHTML = '<i class="fas fa-redo me-2"></i>Try Again';
          uploadButton.disabled = false;
        });
      }
      
      // Refresh S3 content without full page reload
      function refreshS3Content() {
        showLoading("Refreshing content...");
        
        fetch('/upload/get-s3-content')
          .then(response => response.json())
          .then(data => {
            hideLoading();
            if (data.success) {
              // Replace the content of s3Content with the updated HTML
              document.getElementById('s3Content').innerHTML = data.html;
              
              // Reattach event handlers
              attachEventHandlers();
              
              showNotification("Content refreshed successfully", "success");
            } else {
              showNotification("Failed to refresh content: " + data.message, "danger");
            }
          })
          .catch(error => {
            hideLoading();
            console.error('Error refreshing content:', error);
            showNotification("Error refreshing content. Please try again.", "danger");
          });
      }

      // Delete folder functionality
      function attachEventHandlers() {
        // Delete button handlers
        document.querySelectorAll('.delete-folder').forEach(button => {
          button.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Get folder name from data attribute
            const folderToDelete = this.getAttribute('data-folder');
            
            // Update the modal text
            document.getElementById('folderNameToDelete').textContent = folderToDelete;
            
            // Show the confirmation modal
            deleteModal.show();
            
            // Setup confirm button
            document.getElementById('confirmDeleteBtn').onclick = function() {
              deleteFolder(folderToDelete);
            };
          });
        });
        
        // Rename button handlers
        document.querySelectorAll('.rename-folder').forEach(button => {
          button.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Get folder name from data attribute
            const folderToRename = this.getAttribute('data-folder');
            
            // Update the modal text
            document.getElementById('currentFolderName').textContent = folderToRename;
            document.getElementById('newFolderName').value = folderToRename;
            
            // Show the confirmation modal
            renameModal.show();
            
            // Setup confirm button
            document.getElementById('confirmRenameBtn').onclick = function() {
              renameFolder(folderToRename, document.getElementById('newFolderName').value.trim());
            };
          });
        });
        
        // Download button handlers
        document.querySelectorAll('.download-folder').forEach(button => {
          button.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Get folder name from data attribute
            const folderToDownload = this.getAttribute('data-folder');
            
            // Trigger download
            downloadFolder(folderToDownload);
          });
        });
        
        // Setup batch mode checkboxes
        if (document.getElementById('batchModeToggle').checked) {
          document.querySelectorAll('.folder-select-checkbox').forEach(checkbox => {
            checkbox.classList.remove('d-none');
          });
          document.getElementById('batchActionsContainer').style.display = 'block';
        }
      }
      
      // Attach event handlers on page load
      document.addEventListener('DOMContentLoaded', function() {
        attachEventHandlers();
        
        // Batch mode toggle
        document.getElementById('batchModeToggle').addEventListener('change', function() {
          const checkboxes = document.querySelectorAll('.folder-select-checkbox');
          const batchActionsContainer = document.getElementById('batchActionsContainer');
          
          if (this.checked) {
            // Show checkboxes and batch actions
            checkboxes.forEach(checkbox => checkbox.classList.remove('d-none'));
            batchActionsContainer.style.display = 'block';
          } else {
            // Hide checkboxes and batch actions
            checkboxes.forEach(checkbox => checkbox.classList.add('d-none'));
            batchActionsContainer.style.display = 'none';
          }
        });
        
        // Select/Deselect All buttons
        document.getElementById('selectAllBtn').addEventListener('click', function() {
          document.querySelectorAll('.folder-select-checkbox input').forEach(checkbox => {
            checkbox.checked = true;
          });
          updateSelectedCount();
        });
        
        document.getElementById('deselectAllBtn').addEventListener('click', function() {
          document.querySelectorAll('.folder-select-checkbox input').forEach(checkbox => {
            checkbox.checked = false;
          });
          updateSelectedCount();
        });
        
        // Selection count and batch operation buttons
        document.addEventListener('change', function(e) {
          if (e.target.matches('.folder-select-checkbox input')) {
            updateSelectedCount();
          }
        });
        
        // Batch delete button
        document.getElementById('deleteSelectedBtn').addEventListener('click', function() {
          const selectedFolders = getSelectedFolders();
          if (selectedFolders.length === 0) return;
          
          // Update the modal text
          document.getElementById('folderCountToDelete').textContent = selectedFolders.length;
          
          // Update the folders list
          const listEl = document.getElementById('foldersToDeleteList');
          listEl.innerHTML = '';
          selectedFolders.forEach(folder => {
            const folderItem = document.createElement('div');
            folderItem.innerHTML = `<i class="fas fa-folder me-2"></i>${folder}`;
            listEl.appendChild(folderItem);
          });
          
          // Show the confirmation modal
          batchDeleteModal.show();
          
          // Setup confirm button
          document.getElementById('confirmBatchDeleteBtn').onclick = function() {
          deleteMultipleFolders(selectedFolders);
          };
        });
        
        // Batch download button
        document.getElementById('downloadSelectedBtn').addEventListener('click', function() {
          const selectedFolders = getSelectedFolders();
          if (selectedFolders.length === 0) return;
          
          // For now, we only support downloading one folder at a time
          if (selectedFolders.length === 1) {
            downloadFolder(selectedFolders[0]);
          } else {
            showNotification("Batch download is not yet supported. Please select just one folder.", "warning");
          }
        });
        
        // Sort and filter
        document.getElementById('sortBySelect').addEventListener('change', sortFolders);
        document.getElementById('filterInput').addEventListener('input', filterFolders);
      });
      
      // Get selected folders
      function getSelectedFolders() {
        const selectedCheckboxes = document.querySelectorAll('.folder-select-checkbox input:checked');
        return Array.from(selectedCheckboxes).map(checkbox => checkbox.value);
      }
      
      // Update selected count and button states
      function updateSelectedCount() {
        const selectedFolders = getSelectedFolders();
        const count = selectedFolders.length;
        
        // Update the count display
        document.getElementById('selectedCount').textContent = `${count} folder${count !== 1 ? 's' : ''} selected`;
        
        // Update button states
        document.getElementById('deleteSelectedBtn').disabled = count === 0;
        document.getElementById('downloadSelectedBtn').disabled = count === 0;
      }
      
      // Delete a single folder
      function deleteFolder(folderName) {
        // Show loading
        showLoading("Deleting folder...");
        deleteModal.hide();
        
        fetch('/upload/delete-folder', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            folder: folderName
          })
        })
        .then(response => response.json())
        .then(data => {
          hideLoading();
          
          if (data.success) {
            showNotification(`Folder "${folderName}" successfully deleted.`, "success");
            
            // Remove the folder card from the UI
            const folderCard = document.querySelector(`.folder-item[data-folder="${folderName}"]`);
            if (folderCard) {
              folderCard.remove();
            }
            
            // Check if no folders left
            if (document.querySelectorAll('.folder-item').length === 0) {
              document.getElementById('s3Content').innerHTML = `
                <div class="col-12">
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No content found in S3. Upload content using the Upload tab.
                  </div>
                </div>
              `;
            }
          } else {
            showNotification(`Error: ${data.message}`, "danger");
          }
        })
        .catch(error => {
          hideLoading();
          console.error('Error deleting folder:', error);
          showNotification("Failed to delete folder. Please try again.", "danger");
        });
      }
      
      // Delete multiple folders
      function deleteMultipleFolders(folderNames) {
        // Show loading
        showLoading(`Deleting ${folderNames.length} folders...`);
        batchDeleteModal.hide();
        
        fetch('/upload/batch-delete', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            folders: folderNames
          })
        })
        .then(response => response.json())
        .then(data => {
          hideLoading();
          
          if (data.success) {
            showNotification(`Successfully deleted ${data.deleted_count} folders.`, "success");
            
            // Remove the folder cards from the UI
            folderNames.forEach(folderName => {
              const folderCard = document.querySelector(`.folder-item[data-folder="${folderName}"]`);
              if (folderCard) {
                folderCard.remove();
              }
            });
            
            // Reset checkboxes
            document.querySelectorAll('.folder-select-checkbox input').forEach(checkbox => {
              checkbox.checked = false;
            });
            updateSelectedCount();
            
            // Check if no folders left
            if (document.querySelectorAll('.folder-item').length === 0) {
              document.getElementById('s3Content').innerHTML = `
                <div class="col-12">
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No content found in S3. Upload content using the Upload tab.
                  </div>
                </div>
              `;
            }
          } else {
            showNotification(`Error: ${data.message}`, "danger");
          }
        })
        .catch(error => {
          hideLoading();
          console.error('Error deleting folders:', error);
          showNotification("Failed to delete folders. Please try again.", "danger");
        });
      }
      
      // Rename a folder
      function renameFolder(oldName, newName) {
        // Basic validation
        if (!newName) {
          document.getElementById('newFolderName').classList.add('is-invalid');
          return;
        }
        
        // Validate folder name (letters, numbers, underscores, hyphens)
        if (!/^[a-zA-Z0-9_-]+$/.test(newName)) {
          document.getElementById('newFolderName').classList.add('is-invalid');
          return;
        }
        
        // Show loading
        showLoading("Renaming folder...");
        renameModal.hide();
        
        fetch('/upload/rename-folder', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            old_name: oldName,
            new_name: newName
          })
        })
        .then(response => response.json())
        .then(data => {
          hideLoading();
          
          if (data.success) {
            showNotification(`Folder renamed from "${oldName}" to "${newName}".`, "success");
            
            // Refresh the content
            refreshS3Content();
          } else {
            showNotification(`Error: ${data.message}`, "danger");
          }
        })
        .catch(error => {
          hideLoading();
          console.error('Error renaming folder:', error);
          showNotification("Failed to rename folder. Please try again.", "danger");
        });
      }
      
      // Download a folder as ZIP
      function downloadFolder(folderName) {
        showLoading(`Preparing ${folderName} for download...`);
        
        // Create a link to trigger the download
        const downloadLink = document.createElement('a');
        downloadLink.href = `/upload/download-folder?folder=${encodeURIComponent(folderName)}`;
        downloadLink.setAttribute('download', `${folderName}.zip`);
        document.body.appendChild(downloadLink);
        
        // Click the link to start the download
        downloadLink.click();
        
        // Clean up
        document.body.removeChild(downloadLink);
        
        // Hide loading after a short delay to account for browser download dialog
        setTimeout(() => {
          hideLoading();
          showNotification(`Download initiated for folder "${folderName}".`, "success");
        }, 1000);
      }
      
      // Sort folders
      function sortFolders() {
        const sortBy = document.getElementById('sortBySelect').value;
        const folderItems = Array.from(document.querySelectorAll('.folder-item'));
        const container = document.getElementById('s3Content');
        
        // Remove all folder items
        folderItems.forEach(item => container.removeChild(item));
        
        // Sort the items
        folderItems.sort((a, b) => {
          const folderA = a.getAttribute('data-folder').toLowerCase();
          const folderB = b.getAttribute('data-folder').toLowerCase();
          const timestampA = parseFloat(a.getAttribute('data-timestamp') || 0);
          const timestampB = parseFloat(b.getAttribute('data-timestamp') || 0);
          const countA = a.querySelectorAll('.file-item').length;
          const countB = b.querySelectorAll('.file-item').length;
          
          switch(sortBy) {
            case 'newest':
              return timestampB - timestampA;
            case 'oldest':
              return timestampA - timestampB;
            case 'name-asc':
              return folderA.localeCompare(folderB);
            case 'name-desc':
              return folderB.localeCompare(folderA);
            case 'count':
              return countB - countA;
            default:
              return 0;
          }
        });
        
        // Add the sorted items back
        folderItems.forEach(item => container.appendChild(item));
      }
      
      // Filter folders
      function filterFolders() {
        const filterText = document.getElementById('filterInput').value.toLowerCase();
        const folderItems = document.querySelectorAll('.folder-item');
        
        folderItems.forEach(item => {
          const folderName = item.getAttribute('data-folder').toLowerCase();
          
          if (folderName.includes(filterText)) {
            item.style.display = '';
          } else {
            item.style.display = 'none';
          }
        });
      }
    </script>
  </body>
</html>
"""

@app.route("/")
def index():
    """Redirect to dashboard page."""
    return redirect(url_for('upload_dashboard.dashboard'))

@app.route("/dashboard")
def dashboard():
    """Main dashboard page."""
    s3_content = get_s3_content() if has_s3_config else []
    
    return render_template_string(
        HTML_TEMPLATE, 
        s3_content=s3_content,
        has_s3_config=has_s3_config
    )

@app.route("/get-s3-content")
def get_s3_content_route():
    """API endpoint to get S3 content for refreshing."""
    try:
        s3_content = get_s3_content() if has_s3_config else []
        
        # Render just the S3 content section as HTML
        from flask import render_template
        html = render_template_string("""
            {% if s3_content %}
                {% for item in s3_content %}
                  <div class="col-md-4 folder-item" data-folder="{{ item.folder }}" data-timestamp="{{ item.timestamp }}">
                    <div class="card content-card">
                      <!-- Checkbox for batch operations (hidden initially) -->
                      <div class="form-check folder-select-checkbox d-none">
                        <input class="form-check-input" type="checkbox" value="{{ item.folder }}" id="folder-check-{{ loop.index }}">
                      </div>
                      
                      <div class="card-header d-flex justify-content-between align-items-center">
                        <span class="truncate" title="{{ item.folder }}">{{ item.folder }}</span>
                        <div class="actions-menu">
                          <div class="dropdown">
                            <button class="btn btn-sm" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                              <i class="fas fa-ellipsis-v"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end">
                              <li><a class="dropdown-item rename-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-edit me-2"></i>Rename
                              </a></li>
                              <li><a class="dropdown-item download-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-download me-2"></i>Download as ZIP
                              </a></li>
                              <li><hr class="dropdown-divider"></li>
                              <li><a class="dropdown-item text-danger delete-folder" href="#" data-folder="{{ item.folder }}">
                                <i class="fas fa-trash-alt me-2"></i>Delete
                              </a></li>
                            </ul>
                          </div>
                        </div>
                      </div>
                      <div class="card-body">
                        {% if item.image_files %}
                          <p><strong><i class="fas fa-image me-2" style="color: #40C4FF;"></i>Images:</strong> {{ item.image_files|length }}</p>
                          <div class="file-container">
                            {% for file in item.image_files[:3] %}
                              <div class="file-item">
                                <i class="fas fa-file-image me-1" style="color: #40C4FF;"></i> {{ file }}
                              </div>
                            {% endfor %}
                            {% if item.image_files|length > 3 %}
                              <small class="text-muted">And {{ item.image_files|length - 3 }} more...</small>
                            {% endif %}
                          </div>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-image me-2"></i>No images</p>
                        {% endif %}
                        
                        {% if item.text_files %}
                          <p><strong><i class="fas fa-file-alt me-2" style="color: #78909C;"></i>Text files:</strong> {{ item.text_files|length }}</p>
                          <div class="file-container">
                            {% for file in item.text_files[:3] %}
                              <div class="file-item">
                                <i class="fas fa-file-alt me-1" style="color: #78909C;"></i> {{ file }}
                              </div>
                            {% endfor %}
                            {% if item.text_files|length > 3 %}
                              <small class="text-muted">And {{ item.text_files|length - 3 }} more...</small>
                            {% endif %}
                          </div>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-file-alt me-2"></i>No text files</p>
                        {% endif %}
                        
                        <div class="date-info mt-2">
                          <i class="fas fa-clock me-1"></i> {{ item.last_modified.strftime('%Y-%m-%d %H:%M:%S') if item.last_modified else 'Unknown date' }}
                        </div>
                      </div>
                    </div>
                  </div>
                {% endfor %}
              {% else %}
                <div class="col-12">
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No content found in S3. Upload content using the Upload tab.
                  </div>
                </div>
              {% endif %}
        """, s3_content=s3_content)
        
        return jsonify({
            "success": True,
            "html": html
        })
    except Exception as e:
        logger.error(f"Error getting S3 content: {e}")
        return jsonify({
            "success": False,
            "message": f"Error retrieving content: {str(e)}"
        })

@app.route("/upload-files", methods=["POST"])
def upload_files():
    """Handle file uploads via AJAX with direct S3 upload."""
    try:
        # Add detailed logging for request diagnostics
        logger.info(f"Upload request received with Content-Type: {request.content_type}")
        logger.info(f"Files in request: {list(request.files.keys())}")
        logger.info(f"Form data keys: {list(request.form.keys())}")
        
        if 'images' not in request.files or 'texts' not in request.files:
            logger.error(f"Missing required file types. Available keys: {list(request.files.keys())}")
            return jsonify({"success": False, "message": "No files uploaded"})
        
        images = request.files.getlist('images')
        texts = request.files.getlist('texts')
        
        # Log details about the files received
        logger.info(f"Received {len(images)} image(s) and {len(texts)} text file(s)")
        for i, img in enumerate(images):
            logger.info(f"Image {i+1}: {img.filename} ({img.content_type})")
        for i, txt in enumerate(texts):
            logger.info(f"Text {i+1}: {txt.filename} ({txt.content_type})")
        
        if len(images) != len(texts):
            logger.error(f"Mismatched counts: {len(images)} images vs {len(texts)} texts")
            return jsonify({"success": False, "message": "Mismatched number of image and text files"})
        
        if not images or not texts:
            logger.error("Empty file lists despite having keys in request")
            return jsonify({"success": False, "message": "No files selected"})
        
        # Check if S3 is configured
        if not has_s3_config:
            logger.error("S3 is not configured, cannot upload files")
            return jsonify({"success": False, "message": "S3 storage is not configured. Please check your environment variables."})
        
        # Validate files
        for i, (image_file, text_file) in enumerate(zip(images, texts)):
            if not allowed_file(image_file.filename) or not allowed_file(text_file.filename):
                logger.error(f"Invalid file type: {image_file.filename} or {text_file.filename}")
                return jsonify({"success": False, "message": "Invalid file type. Allowed: jpg, jpeg, png, txt"})
            
            # Get base names without extensions
            image_base = os.path.splitext(secure_filename(image_file.filename))[0]
            text_base = os.path.splitext(secure_filename(text_file.filename))[0]
            
            logger.info(f"Comparing base names: '{image_base}' vs '{text_base}'")
            
            # Verify matching base names
            if image_base != text_base:
                logger.error(f"File base names do not match: '{image_base}' vs '{text_base}'")
                return jsonify({"success": False, "message": f"File names do not match: {image_file.filename} and {text_file.filename}"})
        
        # Get custom folder name or create a default one
        folder_name = request.form.get('folder_name', '').strip()
        if not folder_name:
            folder_name = create_next_folder_name()
        
        # Validate folder name (letters, numbers, underscores, hyphens)
        if not re.match(r'^[a-zA-Z0-9_-]+$', folder_name):
            logger.error(f"Invalid folder name: {folder_name}")
            return jsonify({"success": False, "message": "Invalid folder name. Use only letters, numbers, underscores, and hyphens."})
        
        logger.info(f"Using folder name: {folder_name}")
        
        # Prepare files for S3 upload
        s3_files = []
        for image_file, text_file in zip(images, texts):
            # Reset file positions
            image_file.seek(0)
            text_file.seek(0)
            s3_files.extend([image_file, text_file])
        
        # Upload files directly to S3
        logger.info(f"Uploading {len(s3_files)} files to S3 bucket {S3_BUCKET} with prefix {folder_name}")
        success, upload_count, error_count = upload_files_to_s3(
            s3_files, s3_client, S3_BUCKET, s3_prefix=folder_name
        )
        
        if not success:
            logger.error(f"S3 upload failed. {error_count} errors occurred.")
            return jsonify({"success": False, "message": f"Failed to upload files to S3. Please try again."})
        
        logger.info(f"Successfully uploaded {upload_count} files to S3 in folder {folder_name}")
        
        return jsonify({
            "success": True, 
            "message": f"Successfully uploaded {len(images)} file pair(s) to S3 folder '{folder_name}'!"
        })
        
    except Exception as e:
        logger.error(f"Error handling file upload: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/delete-folder", methods=["POST"])
def delete_folder_route():
    """Delete a folder from S3."""
    if not request.is_json:
        logger.error("Invalid request format for folder deletion - expected JSON")
        return jsonify({"success": False, "message": "Invalid request format"}), 400
    
    data = request.get_json()
    folder = data.get("folder")
    
    if not folder:
        logger.error("No folder specified for deletion")
        return jsonify({"success": False, "message": "No folder specified"}), 400
    
    if not has_s3_config:
        logger.error("S3 is not configured, cannot delete folder")
        return jsonify({"success": False, "message": "S3 storage is not configured"}), 400
    
    try:
        logger.info(f"Deleting folder {folder} from S3 bucket {S3_BUCKET}")
        success, deleted_count, error_message = delete_folder_from_s3(s3_client, S3_BUCKET, folder)
        
        if success:
            logger.info(f"Successfully deleted folder {folder} with {deleted_count} objects")
            return jsonify({
                "success": True,
                "message": f"Deleted folder '{folder}' from S3 with {deleted_count} objects"
            })
        else:
            logger.error(f"Failed to delete folder {folder}: {error_message}")
            return jsonify({
                "success": False,
                "message": f"Failed to delete folder: {error_message}"
            })
    except Exception as e:
        logger.error(f"Error deleting folder {folder} from S3: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/batch-delete", methods=["POST"])
def batch_delete_route():
    """Delete multiple folders from S3."""
    if not request.is_json:
        logger.error("Invalid request format for batch deletion - expected JSON")
        return jsonify({"success": False, "message": "Invalid request format"}), 400
    
    data = request.get_json()
    folders = data.get("folders", [])
    
    if not folders:
        logger.error("No folders specified for batch deletion")
        return jsonify({"success": False, "message": "No folders specified"}), 400
    
    if not has_s3_config:
        logger.error("S3 is not configured, cannot delete folders")
        return jsonify({"success": False, "message": "S3 storage is not configured"}), 400
    
    try:
        logger.info(f"Batch deleting {len(folders)} folders from S3 bucket {S3_BUCKET}")
        
        success_count = 0
        error_count = 0
        deleted_objects = 0
        
        for folder in folders:
            success, count, error = delete_folder_from_s3(s3_client, S3_BUCKET, folder)
            if success:
                success_count += 1
                deleted_objects += count
            else:
                error_count += 1
                logger.error(f"Failed to delete folder {folder}: {error}")
        
        if error_count == 0:
            logger.info(f"Successfully deleted {success_count} folders with {deleted_objects} objects")
            return jsonify({
                "success": True,
                "message": f"Successfully deleted {success_count} folders",
                "deleted_count": success_count,
                "object_count": deleted_objects
            })
        else:
            logger.warning(f"Partially succeeded: deleted {success_count} folders, failed to delete {error_count} folders")
            return jsonify({
                "success": True,
                "message": f"Partially succeeded: deleted {success_count} folders, failed to delete {error_count} folders",
                "deleted_count": success_count,
                "error_count": error_count
            })
    except Exception as e:
        logger.error(f"Error batch deleting folders from S3: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/rename-folder", methods=["POST"])
def rename_folder_route():
    """Rename a folder in S3."""
    if not request.is_json:
        logger.error("Invalid request format for folder rename - expected JSON")
        return jsonify({"success": False, "message": "Invalid request format"}), 400
    
    data = request.get_json()
    old_name = data.get("old_name")
    new_name = data.get("new_name")
    
    if not old_name or not new_name:
        logger.error("Missing required parameters: old_name or new_name")
        return jsonify({"success": False, "message": "Missing required parameters"}), 400
    
    # Validate new folder name (letters, numbers, underscores, hyphens)
    if not re.match(r'^[a-zA-Z0-9_-]+$', new_name):
        logger.error(f"Invalid folder name: {new_name}")
        return jsonify({"success": False, "message": "Invalid folder name. Use only letters, numbers, underscores, and hyphens."})
    
    if not has_s3_config:
        logger.error("S3 is not configured, cannot rename folder")
        return jsonify({"success": False, "message": "S3 storage is not configured"}), 400
    
    try:
        logger.info(f"Renaming folder {old_name} to {new_name} in S3 bucket {S3_BUCKET}")
        success, renamed_count, error_message = rename_folder_in_s3(s3_client, S3_BUCKET, old_name, new_name)
        
        if success:
            logger.info(f"Successfully renamed folder {old_name} to {new_name} with {renamed_count} objects")
            return jsonify({
                "success": True,
                "message": f"Renamed folder '{old_name}' to '{new_name}' with {renamed_count} objects"
            })
        else:
            logger.error(f"Failed to rename folder {old_name} to {new_name}: {error_message}")
            return jsonify({
                "success": False,
                "message": f"Failed to rename folder: {error_message}"
            })
    except Exception as e:
        logger.error(f"Error renaming folder {old_name} to {new_name}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/download-folder")
def download_folder_route():
    """Download a folder from S3 as a ZIP archive."""
    folder = request.args.get("folder")
    
    if not folder:
        logger.error("No folder specified for download")
        return jsonify({"success": False, "message": "No folder specified"}), 400
    
    if not has_s3_config:
        logger.error("S3 is not configured, cannot download folder")
        return jsonify({"success": False, "message": "S3 storage is not configured"}), 400
    
    try:
        logger.info(f"Creating download archive for folder {folder} from S3 bucket {S3_BUCKET}")
        
        # Create a temporary file to store the ZIP archive
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
        
        # Create the ZIP archive
        success, result, error_message = create_download_archive(s3_client, S3_BUCKET, folder, output_path=temp_path)
        
        if success:
            logger.info(f"Successfully created ZIP archive for folder {folder} at {temp_path}")
            
            # Send the file
            return send_file(
                temp_path,
                as_attachment=True,
                download_name=f"{folder}.zip",
                mimetype='application/zip'
            )
        else:
            logger.error(f"Failed to create download archive for folder {folder}: {error_message}")
            return jsonify({
                "success": False,
                "message": f"Failed to create download archive: {error_message}"
            })
    except Exception as e:
        logger.error(f"Error creating download archive for folder {folder}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5002))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    app.run(debug=True, host=host, port=port)