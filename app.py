import os
import json
from threading import Thread
from datetime import datetime 
import time
from flask import Flask, redirect, render_template_string, url_for, jsonify

# Import your blueprints
from src.dashboard import app as dashboard_blueprint
from src.upload_dashboard import app as upload_blueprint

# Import bot functionality
from src.main import run_scheduler, scheduled_post, monitor_and_engage, send_scheduled_dms

# Create the main Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "defaultsecretkey")

# Register blueprints with their URL prefixes
app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')
app.register_blueprint(upload_blueprint, url_prefix='/upload')

# Bot thread
bot_thread = None

def run_bot_in_background():
    """Run the Twitter bot scheduler in background thread"""
    while True:
        try:
            print("Starting Twitter bot scheduler in background thread...")
            run_scheduler()
            # If run_scheduler exits normally, sleep before restarting
            time.sleep(60)
        except Exception as e:
            print(f"Bot error: {e}")
            # Sleep before restarting
            time.sleep(60)

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
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Twitter Bot Admin Portal</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #f8f9fa;
                    color: #333;
                }}
                .navbar {{
                    background-color: #37474F !important;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .navbar-brand {{
                    color: white !important;
                    font-weight: 600;
                }}
                .hero-section {{
                    background: linear-gradient(135deg, #40C4FF 0%, #80D8FF 100%);
                    padding: 60px 0;
                    color: white;
                    margin-bottom: 40px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .hero-title {{
                    font-size: 2.5rem;
                    font-weight: 700;
                    margin-bottom: 20px;
                }}
                .card {{
                    border: none;
                    border-radius: 10px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.05);
                    transition: transform 0.3s ease, box-shadow 0.3s ease;
                    margin-bottom: 20px;
                    height: 100%;
                }}
                .card:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 8px 16px rgba(0,0,0,0.1);
                }}
                .card-icon {{
                    font-size: 2.5rem;
                    margin-bottom: 15px;
                    color: #40C4FF;
                }}
                .card-title {{
                    color: #37474F;
                    font-weight: 600;
                }}
                .btn-primary {{
                    background-color: #40C4FF;
                    border-color: #40C4FF;
                }}
                .btn-primary:hover {{
                    background-color: #37474F;
                    border-color: #37474F;
                }}
                .btn-secondary {{
                    background-color: #78909C;
                    border-color: #78909C;
                }}
                .btn-secondary:hover {{
                    background-color: #37474F;
                    border-color: #37474F;
                }}
                .status-section {{
                    background-color: #f1f4f7;
                    border-radius: 10px;
                    padding: 20px;
                    margin-top: 40px;
                    margin-bottom: 40px;
                }}
                .status-indicator {{
                    width: 12px;
                    height: 12px;
                    border-radius: 50%;
                    display: inline-block;
                    margin-right: 8px;
                }}
                .status-active {{
                    background-color: #4CAF50;
                }}
                .footer {{
                    background-color: #37474F;
                    color: white;
                    padding: 20px 0;
                    margin-top: 40px;
                }}
                .action-card {{
                    border-left: 4px solid #40C4FF;
                }}
            </style>
        </head>
        <body>
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

            <div class="container">
                <div class="row">
                    <div class="col-md-4 mb-4">
                        <div class="card h-100 text-center p-4">
                            <div class="card-body">
                                <div class="card-icon">
                                    <i class="fas fa-chart-line"></i>
                                </div>
                                <h5 class="card-title">Dashboard</h5>
                                <p class="card-text">Monitor your bot's performance, track engagement metrics, and view detailed analytics.</p>
                                <a href="/dashboard" class="btn btn-primary mt-2">View Dashboard</a>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-md-4 mb-4">
                        <div class="card h-100 text-center p-4">
                            <div class="card-body">
                                <div class="card-icon">
                                    <i class="fas fa-cloud-upload-alt"></i>
                                </div>
                                <h5 class="card-title">Content Upload</h5>
                                <p class="card-text">Upload new images and content for your bot to share on Twitter.</p>
                                <a href="/upload" class="btn btn-primary mt-2">Upload Content</a>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-md-4 mb-4">
                        <div class="card h-100 text-center p-4">
                            <div class="card-body">
                                <div class="card-icon">
                                    <i class="fas fa-robot"></i>
                                </div>
                                <h5 class="card-title">Bot Status</h5>
                                <p class="card-text">Check the operational status of your bot and view detailed diagnostic information.</p>
                                <a href="/bot_status" class="btn btn-primary mt-2">Check Status</a>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="status-section">
                    <h4 class="mb-4"><i class="fas fa-cogs me-2"></i> Manual Controls</h4>
                    <div class="row">
                        <div class="col-md-4 mb-3">
                            <div class="card action-card">
                                <div class="card-body">
                                    <h5 class="card-title"><i class="fas fa-comment-dots me-2"></i> Post Tweet</h5>
                                    <p class="card-text">Manually trigger a tweet post with your latest content.</p>
                                    <a href="/run_post" class="btn btn-secondary">Post Now</a>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4 mb-3">
                            <div class="card action-card">
                                <div class="card-body">
                                    <h5 class="card-title"><i class="fas fa-handshake me-2"></i> Run Engagement</h5>
                                    <p class="card-text">Manually trigger engagement with targeted users.</p>
                                    <a href="/run_engage" class="btn btn-secondary">Engage Now</a>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4 mb-3">
                            <div class="card action-card">
                                <div class="card-body">
                                    <h5 class="card-title"><i class="fas fa-envelope me-2"></i> Send DMs</h5>
                                    <p class="card-text">Manually trigger sending of direct messages.</p>
                                    <a href="/run_dm" class="btn btn-secondary">Send DMs</a>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="text-center mt-5">
                    <div class="status-indicator status-active"></div>
                    <span>Bot system online and operational</span>
                </div>
            </div>

            <footer class="footer mt-5">
                <div class="container text-center">
                    <p>&copy; {datetime.now().year} Twitter Bot. All Rights Reserved.</p>
                </div>
            </footer>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
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
                    margin-top: 40px;
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
        <body>
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
                    <a href="/" class="btn btn-primary me-2">
                        <i class="fas fa-home me-2"></i> Back to Dashboard
                    </a>
                    <a href="/start_bot" class="btn btn-success" onclick="event.preventDefault(); fetch('/start_bot', {method: 'POST'}).then(response => response.json()).then(data => alert(data.status));">
                        <i class="fas fa-play me-2"></i> Restart Bot
                    </a>
                </div>
            </div>

            <footer class="footer">
                <div class="container text-center">
                    <p>&copy; {{ current_year }} Twitter Bot. All Rights Reserved.</p>
                </div>
            </footer>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
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
            </style>
        </head>
        <body>
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

            <div class="container">
                <div class="card error-card">
                    <div class="card-body">
                        <h5 class="card-title text-danger"><i class="fas fa-times-circle me-2"></i> Error Details</h5>
                        <p class="card-text">{str(e)}</p>
                        <div class="mt-4">
                            <a href="/" class="btn btn-primary">
                                <i class="fas fa-home me-2"></i> Return to Dashboard
                            </a>
                        </div>
                    </div>
                </div>
            </div>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
        """

# Start the bot on server startup (for production) 
@app.route('/start_bot', methods=['POST'])
def start_bot_route():
    """Start the bot manually via API call"""
    global bot_thread
    if bot_thread is None or not bot_thread.is_alive():
        bot_thread = Thread(target=run_bot_in_background)
        bot_thread.daemon = True
        bot_thread.start()
        return jsonify({"status": "Bot started in background thread"})
    return jsonify({"status": "Bot already running"})

# Add auto-start logic with Flask 2.x compatible approach
def start_bot_if_production():
    """Start the bot if in production environment"""
    if os.environ.get('FLASK_ENV') != 'development' and os.environ.get('NO_BOT') != 'true':
        global bot_thread
        if bot_thread is None:
            bot_thread = Thread(target=run_bot_in_background)
            bot_thread.daemon = True
            bot_thread.start()
            print("Bot started in background thread")

# Register the startup function
with app.app_context():
    start_bot_if_production()

if __name__ == '__main__':
    # Get port from environment (for Heroku compatibility)
    port = int(os.environ.get('PORT', 5001))
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') == 'development')