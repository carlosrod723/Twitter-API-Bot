import os
import json
from threading import Thread
from datetime import datetime
import time
from flask import Flask, redirect, render_template_string, url_for, jsonify

# Create the main Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "defaultsecretkey")

# Import your blueprints
from src.dashboard import app as dashboard_blueprint
from src.upload_dashboard import app as upload_blueprint
from src.log_viewer import app as log_viewer_blueprint

# Import bot functionality
from src.main import run_scheduler, scheduled_post, monitor_and_engage, send_scheduled_dms

# Register blueprints with their URL prefixes
app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')
app.register_blueprint(upload_blueprint, url_prefix='/upload')
app.register_blueprint(log_viewer_blueprint, url_prefix='/logs')

@app.route("/upload-files", methods=["POST"])
def forward_upload():
    """Forward requests to the correct upload endpoint"""
    return redirect(url_for('upload_dashboard.upload_files'), code=307)  # 307 preserves the POST method

@app.route("/delete-folder", methods=["POST"])
def forward_delete():
    """Forward folder deletion requests to the correct endpoint"""
    return redirect(url_for('upload_dashboard.delete_folder_route'), code=307)
    
@app.route("/rename-folder", methods=["POST"])
def forward_rename():
    """Forward folder rename requests to the correct endpoint"""
    return redirect(url_for('upload_dashboard.rename_folder_route'), code=307)
    
@app.route("/download-folder")
def forward_download():
    """Forward folder download requests to the correct endpoint"""
    return redirect(url_for('upload_dashboard.download_folder_route'))
    
@app.route("/batch-delete", methods=["POST"])
def forward_batch_delete():
    """Forward batch deletion requests to the correct endpoint"""
    return redirect(url_for('upload_dashboard.batch_delete_route'), code=307)

# Enhanced error handling for S3 operations
@app.errorhandler(500)
def handle_s3_error(e):
    """Handle internal server errors, particularly from S3 operations"""
    if "S3" in str(e) or "boto3" in str(e) or "botocore" in str(e):
        app.logger.error(f"S3 operation error: {str(e)}")
        return jsonify({
            "error": "S3 storage operation failed",
            "message": "There was an error communicating with the cloud storage. Please try again later."
        }), 500
    return "Internal Server Error", 500

# Bot thread
bot_thread = None
bot_running = False  # Track if the bot is running

def run_bot_in_background():
    """Run the Twitter bot scheduler in background thread"""
    global bot_running
    bot_running = True
    
    while bot_running:
        try:
            print("Starting Twitter bot cycle in background thread...")
            # Run one cycle of the bot
            scheduled_post()
            monitor_and_engage()
            
            # Sleep between cycles (adjust time as needed)
            print("Bot cycle complete, sleeping for 30 minutes")
            
            # Check in smaller increments so we can stop more responsively
            for _ in range(30):  # 30 minute sleep in 1-minute increments
                if not bot_running:
                    break
                time.sleep(60)
                
        except Exception as e:
            print(f"Bot error: {e}")
            # Sleep before restarting
            time.sleep(60)
    
    print("Bot thread ending")

# Manual control endpoints
@app.route('/run_post')
def trigger_post():
    """Manually trigger a post"""
    try:
        Thread(target=scheduled_post).start()
        return redirect(url_for('admin_portal'))
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/run_engage')
def trigger_engage():
    """Manually trigger engagement"""
    try:
        Thread(target=monitor_and_engage).start()
        return redirect(url_for('admin_portal'))
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/run_dm')
def trigger_dm():
    """Manually trigger DMs"""
    try:
        Thread(target=send_scheduled_dms).start()
        return redirect(url_for('admin_portal'))
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/start_bot', methods=['POST'])
def start_bot_route():
    """Start the bot manually via API call"""
    global bot_thread, bot_running
    
    if bot_running and bot_thread and bot_thread.is_alive():
        return jsonify({"status": "Bot already running", "running": True})
        
    if bot_thread is not None:
        # Clean up any existing thread
        bot_thread = None
    
    # Start a new thread
    bot_thread = Thread(target=run_bot_in_background)
    bot_thread.daemon = True
    bot_thread.start()
    bot_running = True
    return jsonify({"status": "Bot started successfully", "running": True})

@app.route('/stop_bot', methods=['POST'])
def stop_bot_route():
    """Stop the bot manually via API call"""
    global bot_running
    
    # Set the running flag to false - the thread will detect this and exit gracefully
    bot_running = False
    
    return jsonify({"status": "Bot stopping. This may take a moment to complete.", "running": False})

@app.route('/bot_running', methods=['GET'])
def bot_running_status():
    """Check if the bot is currently running"""
    global bot_running, bot_thread
    
    # Check if thread is actually alive
    is_running = bot_running and bot_thread is not None and bot_thread.is_alive()
    
    return jsonify({"running": is_running})

@app.route('/')
def admin_portal():
    """Render the admin portal homepage"""
    try:
        with open('admin-portal/index.html', 'r') as f:
            html_content = f.read()
            
        # Replace placeholder URLs with actual URLs
        html_content = html_content.replace('DASHBOARD_URL', url_for('dashboard.dashboard'))
        html_content = html_content.replace('UPLOAD_URL', url_for('upload_dashboard.index'))
        html_content = html_content.replace('BOT_URL', url_for('bot_status'))
            
        return render_template_string(html_content)
    except Exception as e:
        # Get the current bot running status to initialize the toggle
        try:
            is_running = bot_running and bot_thread is not None and bot_thread.is_alive()
        except:
            is_running = False
            
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Twitter Bot Admin Portal</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f8f9fa;
                    color: #333;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }
                .navbar {
                    background-color: #37474F !important;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .navbar-brand {
                    color: white !important;
                    font-weight: 600;
                }
                .hero-section {
                    background: linear-gradient(135deg, #40C4FF 0%, #80D8FF 100%);
                    padding: 60px 0;
                    color: white;
                    margin-bottom: 40px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }
                .hero-title {
                    font-size: 2.5rem;
                    font-weight: 700;
                    margin-bottom: 20px;
                }
                .card {
                    border: none;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.05);
                    transition: transform 0.3s ease, box-shadow 0.3s ease;
                    margin-bottom: 20px;
                    height: 100%;
                }
                .card:hover {
                    transform: translateY(-5px);
                    box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                }
                .card-icon {
                    font-size: 2.5rem;
                    margin-bottom: 15px;
                    color: #40C4FF;
                }
                .card-title {
                    color: #37474F;
                    font-weight: 600;
                }
                .btn-primary {
                    background-color: #40C4FF;
                    border-color: #40C4FF;
                }
                .btn-primary:hover {
                    background-color: #37474F;
                    border-color: #37474F;
                }
                .status-section {
                    background-color: #f1f4f7;
                    border-radius: 10px;
                    padding: 20px;
                    margin-top: 40px;
                    margin-bottom: 40px;
                }
                .status-indicator {
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    display: inline-block;
                    margin-right: 8px;
                }
                .status-active {
                    background-color: #4CAF50;
                }
                .status-inactive {
                    background-color: #F44336;
                }
                .footer {
                    background-color: #37474F;
                    color: white;
                    padding: 20px 0;
                    margin-top: auto;
                    flex-shrink: 0;
                }
                .action-card {
                    border-left: 4px solid #40C4FF;
                }
                .btn-container {
                    text-align: center;
                    margin-top: auto;
                }
                .content-wrapper {
                    flex: 1 0 auto;
                }
            </style>
        </head>
        <body class="d-flex flex-column min-vh-100">
            <nav class="navbar navbar-dark navbar-expand-lg">
                <div class="container">
                    <a class="navbar-brand" href="/">
                        <i class="fab fa-twitter me-2"></i> Twitter Bot Admin Portal
                    </a>
                </div>
            </nav>

            <section class="hero-section text-center">
                <div class="container">
                    <h1 class="hero-title">Twitter Bot Command Center</h1>
                    <p class="lead">Monitor performance, upload content, and control your bot from one central location.</p>
                </div>
            </section>

            <div class="content-wrapper">
                <div class="container">
                    <div class="row">
                        <div class="col-md-4 mb-4">
                            <div class="card h-100 text-center p-4">
                                <div class="card-body d-flex flex-column">
                                    <div class="card-icon">
                                        <i class="fas fa-chart-line"></i>
                                    </div>
                                    <h5 class="card-title">Dashboard</h5>
                                    <p class="card-text flex-grow-1">Monitor your bot's performance, track engagement metrics, and view detailed analytics.</p>
                                    <div class="btn-container">
                                        <a href="/dashboard" class="btn btn-primary w-75">View Dashboard</a>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-4">
                            <div class="card h-100 text-center p-4">
                                <div class="card-body d-flex flex-column">
                                    <div class="card-icon">
                                        <i class="fas fa-cloud-upload-alt"></i>
                                    </div>
                                    <h5 class="card-title">Content Upload</h5>
                                    <p class="card-text flex-grow-1">Upload new images and content for your bot to share on Twitter.</p>
                                    <div class="btn-container">
                                        <a href="/upload" class="btn btn-primary w-75">Upload Content</a>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="col-md-4 mb-4">
                            <div class="card h-100 text-center p-4">
                                <div class="card-body d-flex flex-column">
                                    <div class="card-icon">
                                        <i class="fas fa-robot"></i>
                                    </div>
                                    <h5 class="card-title">Bot Status</h5>
                                    <p class="card-text flex-grow-1">Check the operational status of your bot and view detailed diagnostic information.</p>
                                    <div class="btn-container">
                                        <a href="/bot_status" class="btn btn-primary w-75">Check Status</a>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="status-section">
                        <h4 class="mb-4"><i class="fas fa-power-off me-2"></i> Bot Control</h4>
                        <div class="row align-items-center">
                            <div class="col-md-6">
                                <div class="d-flex align-items-center">
                                    <div id="bot-status-indicator" class="status-indicator """ + ("status-active" if is_running else "status-inactive") + """"></div>
                                    <span id="bot-status-text">""" + ("Bot is currently running" if is_running else "Bot is currently stopped") + """</span>
                                </div>
                            </div>
                            <div class="col-md-6 text-end">
                                <button id="start-bot-btn" class="btn btn-success me-2" """ + ("style='display:none;'" if is_running else "") + """>
                                    <i class="fas fa-play me-2"></i> Start Bot
                                </button>
                                <button id="stop-bot-btn" class="btn btn-danger" """ + ("" if is_running else "style='display:none;'") + """>
                                    <i class="fas fa-stop me-2"></i> Stop Bot
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- Log Viewer Card in a separate row -->
                    <div class="row">
                        <div class="col-md-12">
                            <div class="card action-card">
                                <div class="card-body d-flex align-items-center">
                                    <div class="flex-grow-1">
                                        <h5 class="card-title"><i class="fas fa-list-alt me-2"></i> Activity Logs</h5>
                                        <p class="card-text mb-0">View real-time logs of your bot's activities including tweets, engagements, and system operations.</p>
                                    </div>
                                    <div>
                                        <a href="/logs" class="btn btn-primary">
                                            <i class="fas fa-eye me-2"></i> View Logs
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="status-section">
                        <h4 class="mb-4"><i class="fas fa-cogs me-2"></i> Manual Controls</h4>
                        <div class="row">
                            <div class="col-md-4 mb-3">
                                <div class="card action-card h-100">
                                    <div class="card-body d-flex flex-column">
                                        <div class="text-center">
                                            <i class="fas fa-comment-dots card-icon"></i>
                                            <h5 class="card-title">Post Tweet</h5>
                                        </div>
                                        <p class="card-text flex-grow-1 text-center">Manually trigger a tweet post with your latest content.</p>
                                        <div class="btn-container">
                                            <a href="/run_post" class="btn btn-primary w-75">Post Now</a>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="card action-card h-100">
                                    <div class="card-body d-flex flex-column">
                                        <div class="text-center">
                                            <i class="fas fa-handshake card-icon"></i>
                                            <h5 class="card-title">Run Engagement</h5>
                                        </div>
                                        <p class="card-text flex-grow-1 text-center">Manually trigger engagement with targeted users.</p>
                                        <div class="btn-container">
                                            <a href="/run_engage" class="btn btn-primary w-75">Engage Now</a>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="card action-card h-100">
                                    <div class="card-body d-flex flex-column">
                                        <div class="text-center">
                                            <i class="fas fa-envelope card-icon"></i>
                                            <h5 class="card-title">Send DMs</h5>
                                        </div>
                                        <p class="card-text flex-grow-1 text-center">Manually trigger sending of direct messages.</p>
                                        <div class="btn-container">
                                            <a href="/run_dm" class="btn btn-primary w-75">Send DMs</a>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <footer class="footer">
                <div class="container text-center">
                    <p class="mb-0">&copy; """ + str(datetime.now().year) + """ Twitter Bot. All Rights Reserved.</p>
                </div>
            </footer>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
            <script>
            // Update bot status on page load
            function updateBotStatus() {
                fetch('/bot_running')
                    .then(response => response.json())
                    .then(data => {
                        const statusIndicator = document.getElementById('bot-status-indicator');
                        const statusText = document.getElementById('bot-status-text');
                        const startBtn = document.getElementById('start-bot-btn');
                        const stopBtn = document.getElementById('stop-bot-btn');
                        
                        if (data.running) {
                            statusIndicator.className = 'status-indicator status-active';
                            statusText.textContent = 'Bot is currently running';
                            startBtn.style.display = 'none';
                            stopBtn.style.display = 'inline-block';
                        } else {
                            statusIndicator.className = 'status-indicator status-inactive';
                            statusText.textContent = 'Bot is currently stopped';
                            startBtn.style.display = 'inline-block';
                            stopBtn.style.display = 'none';
                        }
                    })
                    .catch(error => {
                        console.error('Error checking bot status:', error);
                    });
            }

            document.getElementById('start-bot-btn').addEventListener('click', function() {
                fetch('/start_bot', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.status);
                        updateBotStatus();
                    })
                    .catch(error => {
                        console.error('Error starting bot:', error);
                        alert('Error starting bot. Please check the logs.');
                    });
            });

            document.getElementById('stop-bot-btn').addEventListener('click', function() {
                fetch('/stop_bot', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.status);
                        updateBotStatus();
                    })
                    .catch(error => {
                        console.error('Error stopping bot:', error);
                        alert('Error stopping bot. Please check the logs.');
                    });
            });

            // Check status when page loads
            document.addEventListener('DOMContentLoaded', function() {
                updateBotStatus();
                // Refresh status every 30 seconds
                setInterval(updateBotStatus, 30000);
            });
            </script>
        </body>
        </html>
        """

@app.route('/bot_status')
def bot_status():
    """Show status of the Twitter bot"""
    from src.twitter_bot import TwitterBot
    import json
    
    try:
        bot = TwitterBot()
        status = bot.get_status()
        return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Twitter Bot Status</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            <style>
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f8f9fa;
                    color: #333;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }
                .navbar {
                    background-color: #37474F !important;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .navbar-brand {
                    color: white !important;
                    font-weight: 600;
                }
                .header-section {
                    background: linear-gradient(135deg, #40C4FF 0%, #80D8FF 100%);
                    padding: 40px 0;
                    color: white;
                    margin-bottom: 40px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }
                .content-wrapper {
                    flex: 1 0 auto;
                }
                .status-card {
                    border: none;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.05);
                    margin-bottom: 20px;
                }
                .card-header {
                    background-color: #78909C;
                    color: white;
                    font-weight: 600;
                    border-top-left-radius: 10px !important;
                    border-top-right-radius: 10px !important;
                }
                .json-display {
                    background-color: #f1f4f7;
                    border-radius: 8px;
                    padding: 15px;
                    font-family: 'Courier New', monospace;
                    max-height: 500px;
                    overflow-y: auto;
                }
                .btn-primary {
                    background-color: #40C4FF;
                    border-color: #40C4FF;
                }
                .btn-primary:hover {
                    background-color: #37474F;
                    border-color: #37474F;
                }
                .footer {
                    background-color: #37474F;
                    color: white;
                    padding: 20px 0;
                    margin-top: auto;
                    flex-shrink: 0;
                }
                .status-indicator {
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    display: inline-block;
                    margin-right: 8px;
                }
                .status-active {
                    background-color: #4CAF50;
                }
                .status-warning {
                    background-color: #FFC107;
                }
                .status-error {
                    background-color: #F44336;
                }
            </style>
        </head>
        <body class="d-flex flex-column min-vh-100">
            <nav class="navbar navbar-dark navbar-expand-lg">
                <div class="container">
                    <a class="navbar-brand" href="/">
                        <i class="fab fa-twitter me-2"></i> Twitter Bot Admin Portal
                    </a>
                </div>
            </nav>

            <section class="header-section">
                <div class="container">
                    <h1><i class="fas fa-robot me-2"></i> Bot Status</h1>
                    <p class="lead">Detailed diagnostic information and performance metrics.</p>
                </div>
            </section>

            <div class="content-wrapper">
                <div class="container mb-5">
                    <div class="row mb-4">
                        <div class="col-md-6">
                            <div class="card status-card">
                                <div class="card-header">
                                    <i class="fas fa-info-circle me-2"></i> System Status
                                </div>
                                <div class="card-body">
                                    <div class="d-flex align-items-center mb-3">
                                        <div class="status-indicator status-active"></div>
                                        <strong>Bot System: Online</strong>
                                    </div>
                                    <div class="d-flex align-items-center mb-3">
                                        <div class="status-indicator status-active"></div>
                                        <strong>Twitter API: Connected</strong>
                                    </div>
                                    <div class="d-flex align-items-center">
                                        <div class="status-indicator status-active"></div>
                                        <strong>Database: Connected</strong>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="card status-card">
                                <div class="card-header">
                                    <i class="fas fa-tachometer-alt me-2"></i> Performance Metrics
                                </div>
                                <div class="card-body">
                                    <p><strong>Last Run:</strong> {{ status.get("last_run", "N/A") }}</p>
                                    <p><strong>Next Scheduled Post:</strong> {{ status.get("next_post", "N/A") }}</p>
                                    <p><strong>Engagement Rate:</strong> {{ status.get("engagement_rate", "N/A") }}</p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="card status-card">
                        <div class="card-header">
                            <i class="fas fa-code me-2"></i> Detailed Status Data
                        </div>
                        <div class="card-body">
                            <div class="json-display">
                                <pre>{{ status_json }}</pre>
                            </div>
                        </div>
                    </div>

                    <div class="text-center mt-4">
                        <a href="/" class="btn me-2" style="background-color: #1E90FF; border-color: #1E90FF; color: white;">
                            <i class="fas fa-home me-2"></i> Return to Admin Portal
                        </a>
                        <a href="#" class="btn btn-success" onclick="event.preventDefault(); fetch('/start_bot', {method: 'POST'}).then(response => response.json()).then(data => { alert(data.status); updateBotStatus(); });">
                            <i class="fas fa-play me-2"></i> Restart Bot
                        </a>
                    </div>
                </div>
            </div>

            <footer class="footer">
                <div class="container text-center">
                    <p class="mb-0">&copy; {{ current_year }} Twitter Bot. All Rights Reserved.</p>
                </div>
            </footer>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
            <script>
            // Update status when the bot is restarted
            function updateBotStatus() {
                fetch('/bot_running')
                    .then(response => response.json())
                    .then(data => {
                        // If needed, we could update UI elements here based on bot status
                        // For now, we'll just reload the status data to get the freshest information
                        window.location.reload();
                    })
                    .catch(error => {
                        console.error('Error checking bot status:', error);
                    });
            }
            
            // Auto-refresh status every 60 seconds
            setInterval(function() {
                fetch('/bot_running')
                    .then(response => response.json())
                    .then(data => {
                        if (data.running) {
                            // If bot is running, refresh page for latest stats
                            window.location.reload();
                        }
                    });
            }, 60000);
            </script>
        </body>
        </html>
        """, status=status, status_json=json.dumps(status, indent=2), current_year=datetime.now().year)
    except Exception as e:
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Twitter Bot Status</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f8f9fa;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }}
                .navbar {{
                    background-color: #37474F !important;
                }}
                .navbar-brand {{
                    color: white !important;
                }}
                .header-section {{
                    background: linear-gradient(135deg, #40C4FF 0%, #80D8FF 100%);
                    padding: 40px 0;
                    color: white;
                    margin-bottom: 40px;
                }}
                .content-wrapper {{
                    flex: 1 0 auto;
                }}
                .error-card {{
                    border: none;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                }}
                .btn-primary {{
                    background-color: #40C4FF;
                    border-color: #40C4FF;
                }}
                .btn-primary:hover {{
                    background-color: #37474F;
                    border-color: #37474F;
                }}
                .footer {{
                    background-color: #37474F;
                    color: white;
                    padding: 20px 0;
                    margin-top: auto;
                    flex-shrink: 0;
                }}
            </style>
        </head>
        <body class="d-flex flex-column min-vh-100">
            <nav class="navbar navbar-dark navbar-expand-lg">
                <div class="container">
                    <a class="navbar-brand" href="/">
                        <i class="fab fa-twitter me-2"></i> Twitter Bot Admin Portal
                    </a>
                </div>
            </nav>

            <section class="header-section">
                <div class="container">
                    <h1><i class="fas fa-exclamation-triangle me-2"></i> Status Error</h1>
                    <p class="lead">There was a problem retrieving the bot status.</p>
                </div>
            </section>

            <div class="content-wrapper">
                <div class="container">
                    <div class="card error-card">
                        <div class="card-body">
                            <h5 class="card-title text-danger"><i class="fas fa-times-circle me-2"></i> Error Details</h5>
                            <p class="card-text">{str(e)}</p>
                            <div class="mt-4">
                                <a href="/" class="btn btn-primary">
                                    <i class="fas fa-home me-2"></i> Return to Admin Portal
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <footer class="footer">
                <div class="container text-center">
                    <p class="mb-0">&copy; {datetime.now().year} Twitter Bot. All Rights Reserved.</p>
                </div>
            </footer>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
        """

# Auto-start logic with Flask 2.x compatible approach
def start_bot_if_production():
    """Start the bot if in production environment and auto-start is enabled"""
    # Only auto-start if explicitly configured (default to NOT auto-starting)
    if os.environ.get('AUTOSTART_BOT') == 'true' and os.environ.get('NO_BOT') != 'true':
        global bot_thread, bot_running
        if bot_thread is None:
            bot_thread = Thread(target=run_bot_in_background)
            bot_thread.daemon = True
            bot_thread.start()
            bot_running = True
            print("Bot auto-started in background thread")

# Register the startup function
with app.app_context():
    start_bot_if_production()

if __name__ == '__main__':
    # Get port from environment (for Heroku compatibility)
    port = int(os.environ.get('PORT', 5003))
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')