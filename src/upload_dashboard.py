import os
import boto3
from flask import Flask, request, redirect, flash, render_template_string, jsonify
import logging
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from src.upload_to_s3 import upload_folder_to_s3
import uuid
import shutil
import re

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

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    logger.warning("FLASK_SECRET_KEY not set in .env. Using default (insecure for production).")
    app.secret_key = "defaultsecretkey"

# S3 configuration
S3_BUCKET = os.getenv("S3_BUCKET_NAME", os.getenv("BUCKET_NAME"))
S3_REGION = os.getenv("AWS_REGION", os.getenv("BUCKET_REGION"))
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY"))
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

if not all([S3_BUCKET, S3_REGION, AWS_ACCESS_KEY, AWS_SECRET_ACCESS_KEY]):
    logger.warning("Missing S3 configuration in .env file. Some features may not work.")
    has_s3_config = False
else:
    has_s3_config = True
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION
    )

# Local folders configuration
UPLOAD_FOLDER = "uploads"
TEMP_FOLDER = os.path.join(UPLOAD_FOLDER, "temp")
LOCAL_TEST_DATA = "local_test_data"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)
os.makedirs(LOCAL_TEST_DATA, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload size
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "txt"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_local_content():
    """Get a list of all local content folders and files"""
    content = []
    try:
        for folder_name in os.listdir(LOCAL_TEST_DATA):
            folder_path = os.path.join(LOCAL_TEST_DATA, folder_name)
            if os.path.isdir(folder_path):
                files = os.listdir(folder_path)
                image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                text_files = [f for f in files if f.lower().endswith('.txt')]
                
                content.append({
                    'folder': folder_name,
                    'image_files': image_files,
                    'text_files': text_files,
                    'path': folder_path
                })
    except Exception as e:
        logger.error(f"Error getting local content: {e}")
    
    return content

def get_s3_content():
    """Get a list of all content stored in S3"""
    content = []
    if not has_s3_config:
        return content
    
    try:
        # List all objects in the bucket
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET)
        
        if 'Contents' in response:
            # Group by folder
            folders = {}
            for item in response['Contents']:
                key = item['Key']
                parts = key.split('/')
                
                if len(parts) > 1:
                    folder = parts[0]
                    filename = parts[-1]
                    if folder not in folders:
                        folders[folder] = {
                            'image_files': [],
                            'text_files': []
                        }
                    
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
                    's3_path': f"s3://{S3_BUCKET}/{folder}/"
                })
    except Exception as e:
        logger.error(f"Error getting S3 content: {e}")
    
    return content

def create_next_folder_name():
    """Create the next available folder name based on existing folders"""
    try:
        folders = os.listdir(LOCAL_TEST_DATA)
        # Filter for folders named like "folder1", "folder2", etc.
        pattern = re.compile(r"folder(\d+)")
        existing_numbers = [int(pattern.match(f).group(1)) for f in folders if pattern.match(f)]
        
        if not existing_numbers:
            next_number = 1
        else:
            next_number = max(existing_numbers) + 1
        
        return f"folder{next_number}"
    except Exception as e:
        logger.error(f"Error creating next folder name: {e}")
        # Fallback to timestamp-based name
        return f"folder_{uuid.uuid4().hex[:8]}"

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
      <h1 class="mb-4" style="color: #37474F;">Comic Art Content Manager</h1>
      
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
      
      <ul class="nav nav-tabs" id="myTab" role="tablist">
        <li class="nav-item" role="presentation">
          <button class="nav-link active" id="upload-tab" data-bs-toggle="tab" data-bs-target="#upload" type="button" role="tab">
            <i class="fas fa-upload me-2"></i>Upload Content
          </button>
        </li>
        <li class="nav-item" role="presentation">
          <button class="nav-link" id="local-tab" data-bs-toggle="tab" data-bs-target="#local" type="button" role="tab">
            <i class="fas fa-folder me-2"></i>Local Content
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
              
              <div id="previewContainer" class="preview-container"></div>
              
              <button id="uploadButton" class="btn btn-upload mt-3" disabled>Upload Files</button>
            </div>
          </div>
        </div>
        
        <!-- Local Content Tab -->
        <div class="tab-pane fade" id="local" role="tabpanel">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 style="color: #37474F;">
              <i class="fas fa-folder me-2"></i>
              Local Content Library
            </h4>
            <button class="btn btn-sm btn-outline-secondary" onclick="window.location.reload()">
              <i class="fas fa-sync-alt me-1"></i> Refresh
            </button>
          </div>
          <p class="text-muted">Content stored in your local folders that can be used by the Twitter bot.</p>
          
          <div class="row" id="localContent">
            {% if local_content %}
              {% for item in local_content %}
                <div class="col-md-4">
                  <div class="card content-card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                      <span class="truncate">{{ item.folder }}</span>
                      <a href="/upload-to-s3?folder={{ item.folder }}" class="btn btn-sm btn-outline-s3">
                        <i class="fas fa-cloud-upload-alt"></i> Upload to S3
                      </a>
                    </div>
                    <div class="card-body">
                      {% if item.image_files %}
                        <p><strong><i class="fas fa-image me-2" style="color: #40C4FF;"></i>Images:</strong> {{ item.image_files|length }}</p>
                        <p class="truncate"><small>{{ ', '.join(item.image_files) }}</small></p>
                      {% else %}
                        <p class="text-muted"><i class="fas fa-image me-2"></i>No images</p>
                      {% endif %}
                      
                      {% if item.text_files %}
                        <p><strong><i class="fas fa-file-alt me-2" style="color: #78909C;"></i>Text files:</strong> {{ item.text_files|length }}</p>
                        <p class="truncate"><small>{{ ', '.join(item.text_files) }}</small></p>
                      {% else %}
                        <p class="text-muted"><i class="fas fa-file-alt me-2"></i>No text files</p>
                      {% endif %}
                    </div>
                  </div>
                </div>
              {% endfor %}
            {% else %}
              <div class="col-12">
                <div class="alert alert-info">
                  <i class="fas fa-info-circle me-2"></i>
                  No local content found. Upload content using the Upload tab.
                </div>
              </div>
            {% endif %}
          </div>
        </div>
        
        <!-- S3 Content Tab -->
        <div class="tab-pane fade" id="s3" role="tabpanel">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 style="color: #37474F;">
              <i class="fas fa-cloud me-2"></i>
              S3 Cloud Storage
            </h4>
            <button class="btn btn-sm btn-outline-secondary" onclick="window.location.reload()">
              <i class="fas fa-sync-alt me-1"></i> Refresh
            </button>
          </div>
          <p class="text-muted">Content stored in AWS S3 that can be used by the Twitter bot.</p>
          
          <div class="row" id="s3Content">
            {% if has_s3_config %}
              {% if s3_content %}
                {% for item in s3_content %}
                  <div class="col-md-4">
                    <div class="card content-card">
                      <div class="card-header">
                        <span class="truncate">{{ item.folder }}</span>
                      </div>
                      <div class="card-body">
                        {% if item.image_files %}
                          <p><strong><i class="fas fa-image me-2" style="color: #40C4FF;"></i>Images:</strong> {{ item.image_files|length }}</p>
                          <p class="truncate"><small>{{ ', '.join(item.image_files) }}</small></p>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-image me-2"></i>No images</p>
                        {% endif %}
                        
                        {% if item.text_files %}
                          <p><strong><i class="fas fa-file-alt me-2" style="color: #78909C;"></i>Text files:</strong> {{ item.text_files|length }}</p>
                          <p class="truncate"><small>{{ ', '.join(item.text_files) }}</small></p>
                        {% else %}
                          <p class="text-muted"><i class="fas fa-file-alt me-2"></i>No text files</p>
                        {% endif %}
                        
                        <p class="text-muted small truncate">
                          <i class="fas fa-link me-1"></i>
                          {{ item.s3_path }}
                        </p>
                      </div>
                    </div>
                  </div>
                {% endfor %}
              {% else %}
                <div class="col-12">
                  <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No content found in S3. Upload local content to S3 from the Local Content tab.
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
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // Drag and drop functionality
      const dropArea = document.getElementById('drop-area');
      const fileInput = document.getElementById('fileInput');
      const previewContainer = document.getElementById('previewContainer');
      const uploadButton = document.getElementById('uploadButton');
      
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
        
        // Send Ajax request
        fetch('/upload-files', {
          method: 'POST',
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            // Clear preview
            previewContainer.innerHTML = '';
            fileInput.value = '';
            
            // Show success message
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-success';
            alertDiv.innerHTML = `<i class="fas fa-check-circle me-2"></i>${data.message}`;
            previewContainer.appendChild(alertDiv);
            
            // Reset button
            uploadButton.innerHTML = '<i class="fas fa-upload me-2"></i>Upload Files';
            uploadButton.disabled = true;
            
            // Refresh content tabs after a delay
            setTimeout(() => {
              window.location.reload();
            }, 2000);
          } else {
            // Show error
            const alertDiv = document.createElement('div');
            alertDiv.className = 'alert alert-danger';
            alertDiv.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i>${data.message}`;
            previewContainer.appendChild(alertDiv);
            
            // Reset button
            uploadButton.innerHTML = '<i class="fas fa-redo me-2"></i>Try Again';
            uploadButton.disabled = false;
          }
        })
        .catch(error => {
          console.error('Error:', error);
          
          // Show error
          const alertDiv = document.createElement('div');
          alertDiv.className = 'alert alert-danger';
          alertDiv.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>An error occurred during upload. Please try again.';
          previewContainer.appendChild(alertDiv);
          
          // Reset button
          uploadButton.innerHTML = '<i class="fas fa-redo me-2"></i>Try Again';
          uploadButton.disabled = false;
        });
      }
    </script>
  </body>
</html>
"""

@app.route("/", methods=["GET"])
def dashboard():
    """Main dashboard page."""
    local_content = get_local_content()
    s3_content = get_s3_content() if has_s3_config else []
    
    return render_template_string(
        HTML_TEMPLATE, 
        local_content=local_content,
        s3_content=s3_content,
        has_s3_config=has_s3_config
    )

@app.route("/upload-files", methods=["POST"])
def upload_files():
    """Handle file uploads via AJAX."""
    if 'images' not in request.files or 'texts' not in request.files:
        return jsonify({"success": False, "message": "No files uploaded"})
    
    images = request.files.getlist('images')
    texts = request.files.getlist('texts')
    
    if len(images) != len(texts):
        return jsonify({"success": False, "message": "Mismatched number of image and text files"})
    
    if not images or not texts:
        return jsonify({"success": False, "message": "No files selected"})
    
    try:
        # Create new folder for uploaded content
        folder_name = create_next_folder_name()
        folder_path = os.path.join(LOCAL_TEST_DATA, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        # Save all files
        for i, (image_file, text_file) in enumerate(zip(images, texts)):
            if not allowed_file(image_file.filename) or not allowed_file(text_file.filename):
                return jsonify({"success": False, "message": "Invalid file type. Allowed: jpg, jpeg, png, txt"})
            
            # Get base names without extensions
            image_base = os.path.splitext(secure_filename(image_file.filename))[0]
            text_base = os.path.splitext(secure_filename(text_file.filename))[0]
            
            # Verify matching base names
            if image_base != text_base:
                return jsonify({"success": False, "message": f"File names do not match: {image_file.filename} and {text_file.filename}"})
            
            # Save files
            image_path = os.path.join(folder_path, secure_filename(image_file.filename))
            text_path = os.path.join(folder_path, secure_filename(text_file.filename))
            
            image_file.save(image_path)
            text_file.save(text_path)
            logger.info(f"Saved files to {folder_path}: {image_file.filename}, {text_file.filename}")
        
        # Upload to S3 if configured
        if has_s3_config:
            try:
                upload_folder_to_s3(folder_path, s3_client, S3_BUCKET, s3_prefix=folder_name)
                logger.info(f"Uploaded folder {folder_name} to S3")
            except Exception as s3_error:
                logger.error(f"Error uploading to S3: {s3_error}")
                # Continue anyway since local files are saved
        
        return jsonify({
            "success": True, 
            "message": f"Successfully saved {len(images)} file pair(s) to {folder_name}!" + 
                       (f" and uploaded to S3" if has_s3_config else "")
        })
        
    except Exception as e:
        logger.error(f"Error handling file upload: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/upload-to-s3", methods=["GET"])
def upload_folder_to_s3_route():
    """Upload a specific local folder to S3."""
    if not has_s3_config:
        flash("S3 is not configured. Please check your .env file.", "danger")
        return redirect("/")
    
    folder = request.args.get("folder")
    if not folder:
        flash("No folder specified.", "danger")
        return redirect("/")
    
    folder_path = os.path.join(LOCAL_TEST_DATA, folder)
    if not os.path.isdir(folder_path):
        flash(f"Folder {folder} does not exist.", "danger")
        return redirect("/")
    
    try:
        upload_folder_to_s3(folder_path, s3_client, S3_BUCKET, s3_prefix=folder)
        flash(f"Folder {folder} successfully uploaded to S3!", "success")
    except Exception as e:
        logger.error(f"Error uploading folder {folder} to S3: {e}")
        flash(f"Error uploading to S3: {str(e)}", "danger")
    
    return redirect("/")

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5002))
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    app.run(debug=True, host=host, port=port)