# src/log_viewer.py
import os
import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template_string, jsonify, request
import logging

# Create the blueprint
app = Blueprint('log_viewer', __name__)

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# File paths from environment variables, with fallbacks
LOG_FILE = os.getenv("MAIN_LOG_FILE", "main.log")
MAX_LINES = 500  # Maximum lines to read

@app.route('/')
def view_logs():
    """Render the log viewer page"""
    return render_template_string(LOG_VIEWER_TEMPLATE)

@app.route('/api/logs')
def get_logs():
    """API endpoint to get log entries"""
    log_type = request.args.get('type', None)
    hours = request.args.get('hours', 24, type=int)
    
    logs = read_logs(MAX_LINES, log_type=log_type, hours=hours)
    return jsonify({"logs": logs})

def read_logs(max_lines=100, log_type=None, hours=24):
    """Read and parse log entries from the log file"""
    if not os.path.exists(LOG_FILE):
        return []
    
    # Calculate the cutoff time
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    # Read the file from the end
    try:
        with open(LOG_FILE, 'r') as f:
            from collections import deque
            lines = deque(f, max_lines)
        
        # Parse important log entries
        logs = []
        for line in lines:
            # Parse timestamp, level, and message
            match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (.+)', line)
            if match:
                timestamp_str, level, message = match.groups()
                
                # Parse timestamp
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                    # Skip if older than cutoff
                    if timestamp < cutoff_time:
                        continue
                except ValueError:
                    # If timestamp parsing fails, keep the entry anyway
                    timestamp = datetime.now()
                
                # Determine log entry type for filtering
                entry_type = get_log_type(message)
                
                # Filter by type if specified
                if log_type and entry_type != log_type:
                    continue
                
                # Only include important logs
                if is_important_log(message):
                    logs.append({
                        "timestamp": timestamp_str,
                        "level": level,
                        "message": message,
                        "type": entry_type,
                        "formatted_time": timestamp.strftime('%H:%M:%S')
                    })
        
        # Sort logs by timestamp, newest first
        logs.sort(key=lambda x: x["timestamp"], reverse=True)
        return logs
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return [{"timestamp": str(datetime.now()), "level": "ERROR", "message": f"Error reading logs: {str(e)}"}]

def get_log_type(message):
    """Determine the type of log entry for filtering and display"""
    message_lower = message.lower()
    
    if 'tweet' in message_lower or 'posting' in message_lower:
        return 'tweet'
    elif 'keyword' in message_lower or 'hashtag' in message_lower:
        return 'keyword'
    elif any(word in message_lower for word in ['engagement', 'like', 'retweet', 'comment']):
        return 'engagement'
    elif 'dm' in message_lower or 'direct message' in message_lower:
        return 'dm'
    elif any(word in message_lower for word in ['media', 'image', 'picture', 'upload']):
        return 'media'
    elif 'error' in message_lower or 'exception' in message_lower:
        return 'error'
    else:
        return 'other'

def is_important_log(message):
    """Check if this is an important log that should be displayed"""
    message_lower = message.lower()
    important_keywords = [
        'tweet', 'post', 'found keyword', 'found hashtag', 'found user', 
        'engagement', 'like', 'retweet', 'comment', 'dm sent', 'received dm', 
        'media upload', 'image', 'error', 'exception', 'starting', 'completed',
        'monitoring', 'scheduled'
    ]
    return any(keyword in message_lower for keyword in important_keywords)

# Complete HTML Template for the log viewer page
LOG_VIEWER_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Twitter Bot Activity Logs</title>
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
        margin-bottom: 30px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .content-container {
        flex: 1;
        padding-bottom: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }
    .footer {
        background-color: #37474F;
        color: white;
        padding: 20px 0;
        margin-top: auto;
    }
    .log-card {
        border: none;
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        transition: transform 0.2s, box-shadow 0.2s;
        overflow: hidden;
    }
    .log-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
    }
    .log-card.tweet {
        border-left: 4px solid #1DA1F2;
    }
    .log-card.keyword {
        border-left: 4px solid #17a2b8;
    }
    .log-card.engagement {
        border-left: 4px solid #28a745;
    }
    .log-card.dm {
        border-left: 4px solid #6f42c1;
    }
    .log-card.media {
        border-left: 4px solid #fd7e14;
    }
    .log-card.error {
        border-left: 4px solid #dc3545;
    }
    .log-header {
        padding: 10px 15px;
        font-size: 0.9rem;
        border-bottom: 1px solid #f0f0f0;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .log-body {
        padding: 15px;
    }
    .log-time {
        font-weight: bold;
    }
    .log-type-badge {
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        color: white;
    }
    .log-type-badge.tweet {
        background-color: #1DA1F2;
    }
    .log-type-badge.keyword {
        background-color: #17a2b8;
    }
    .log-type-badge.engagement {
        background-color: #28a745;
    }
    .log-type-badge.dm {
        background-color: #6f42c1;
    }
    .log-type-badge.media {
        background-color: #fd7e14;
    }
    .log-type-badge.error {
        background-color: #dc3545;
    }
    .log-type-badge.other {
        background-color: #6c757d;
    }
    .filter-btn {
        margin-right: 8px;
        margin-bottom: 8px;
        border-radius: 20px;
        padding: 6px 15px;
        background-color: #40C4FF;
        border-color: #40C4FF;
    }
    .filter-btn:hover {
        background-color: #37474F;
        border-color: #37474F;
    }
    .filter-btn.active {
        background-color: #37474F;
        border-color: #37474F;
    }
    .btn-danger {
        background-color: #dc3545;
        border-color: #dc3545;
    }
    .btn-danger:hover {
        background-color: #bb2d3b;
        border-color: #bb2d3b;
    }
    .filter-btn.btn-danger.active {
        background-color: #bb2d3b;
        border-color: #bb2d3b;
    }
    .refresh-section {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
        padding: 15px;
        background-color: #f1f4f7;
        border-radius: 10px;
    }
    .auto-refresh-toggle {
        display: flex;
        align-items: center;
    }
    #refresh-timer {
        font-size: 0.9rem;
        color: #6c757d;
        margin-left: 10px;
    }
    .btn-primary {
        background-color: #40C4FF;
        border-color: #40C4FF;
    }
    .btn-primary:hover {
        background-color: #37474F;
        border-color: #37474F;
    }
    #logContainer {
        min-height: 300px;
    }
    .loader {
        display: flex;
        justify-content: center;
        padding: 20px;
    }
    .no-logs-message {
        text-align: center;
        padding: 30px;
        color: #6c757d;
    }
    .time-filter {
        padding: 6px 12px;
        border-radius: 4px;
        border: 1px solid #ced4da;
        background-color: white;
        margin-right: 10px;
    }
    .form-check-input:checked {
        background-color: #40C4FF;
        border-color: #40C4FF;
    }
    /* Custom Dodger Blue button style */
    .dodger-blue-btn {
        background-color: #1E90FF !important;
        border-color: #1E90FF !important;
        color: white !important;
        font-weight: 500 !important;
        padding: 0.5rem 1rem !important;
        transition: all 0.3s ease !important;
    }
    .dodger-blue-btn:hover {
        background-color: #1a7de2 !important;
        border-color: #1a7de2 !important;
        box-shadow: 0 4px 8px rgba(26, 125, 226, 0.3) !important;
    }
</style>
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
            <h1><i class="fas fa-list-alt me-2"></i> Activity Logs</h1>
            <p class="lead">Monitor your bot's activities in real-time</p>
        </div>
    </section>

    <div class="content-container">
        <div class="container">
            <div class="refresh-section">
                <div class="me-4">
                    <select id="timeFilter" class="time-filter">
                        <option value="24">Last 24 hours</option>
                        <option value="12">Last 12 hours</option>
                        <option value="6">Last 6 hours</option>
                        <option value="1">Last hour</option>
                    </select>
                    <button id="refreshBtn" class="btn btn-primary">
                        <i class="fas fa-sync-alt me-1"></i> Refresh Now
                    </button>
                </div>
                <div class="d-flex align-items-center">
                    <a href="/" class="dodger-blue-btn btn me-4" style="background-color: #1E90FF !important; border-color: #1E90FF !important; color: white !important;">
                        <i class="fas fa-home me-2"></i> Return to Admin Portal
                    </a>
                    <div class="auto-refresh-toggle">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox" id="autoRefreshToggle" checked>
                            <label class="form-check-label" for="autoRefreshToggle">Auto-refresh</label>
                        </div>
                        <span id="refresh-timer">60s</span>
                    </div>
                </div>
            </div>

            <div class="mb-4">
                <button class="btn btn-primary filter-btn active" data-filter="all">All</button>
                <button class="btn btn-primary filter-btn" data-filter="tweet">Tweets</button>
                <button class="btn btn-primary filter-btn" data-filter="keyword">Keywords</button>
                <button class="btn btn-primary filter-btn" data-filter="engagement">Engagements</button>
                <button class="btn btn-primary filter-btn" data-filter="dm">DMs</button>
                <button class="btn btn-primary filter-btn" data-filter="media">Media</button>
                <button class="btn btn-danger filter-btn" data-filter="error">Errors</button>
            </div>

            <div id="logContainer">
                <div class="loader">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <footer class="footer">
        <div class="container text-center">
            <p>&copy; 2025 Twitter Bot. All Rights Reserved.</p>
        </div>
    </footer>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Current filter state
        let currentFilter = 'all';
        let currentTimeFilter = 24;
        let autoRefreshEnabled = true;
        let refreshInterval;
        let refreshCountdown = 15; // Changed to 15 seconds for more responsive updates
        
        // Load logs on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadLogs();
            
            // Check if bot is running to potentially increase refresh rate
            checkBotStatus();
            
            // Set up filter buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    // Update active button
                    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                    this.classList.add('active');
                    
                    // Update filter and reload logs
                    currentFilter = this.getAttribute('data-filter');
                    loadLogs();
                });
            });
            
            // Set up refresh button
            document.getElementById('refreshBtn').addEventListener('click', loadLogs);
            
            // Set up time filter
            document.getElementById('timeFilter').addEventListener('change', function() {
                currentTimeFilter = this.value;
                loadLogs();
            });
            
            // Set up auto-refresh toggle
            document.getElementById('autoRefreshToggle').addEventListener('change', function() {
                autoRefreshEnabled = this.checked;
                if (autoRefreshEnabled) {
                    startAutoRefresh();
                } else {
                    stopAutoRefresh();
                }
            });
            
            // Start auto-refresh
            startAutoRefresh();
        });
        
        // Check if bot is running to adjust refresh rate
        function checkBotStatus() {
            fetch('/bot_running')
                .then(response => response.json())
                .then(data => {
                    if (data.running) {
                        // Bot is running, refresh more frequently (15 seconds)
                        refreshCountdown = 15;
                        if (autoRefreshEnabled) {
                            stopAutoRefresh();
                            startAutoRefresh();
                        }
                    } else {
                        // Bot is not running, use standard refresh (60 seconds)
                        refreshCountdown = 60;
                        if (autoRefreshEnabled) {
                            stopAutoRefresh();
                            startAutoRefresh();
                        }
                    }
                })
                .catch(error => {
                    console.error('Error checking bot status:', error);
                });
                
            // Check bot status every 30 seconds
            setTimeout(checkBotStatus, 30000);
        }
        
        function loadLogs() {
            const logContainer = document.getElementById('logContainer');
            
            // Show loading spinner
            logContainer.innerHTML = `
                <div class="loader">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            `;
            
            // Build the URL with filters
            let url = '/logs/api/logs?hours=' + currentTimeFilter;
            if (currentFilter !== 'all') {
                url += '&type=' + currentFilter;
            }
            
            // Fetch logs
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.logs && data.logs.length > 0) {
                        let html = '';
                        
                        data.logs.forEach(log => {
                            const logTypeClass = log.type || 'other';
                            const logType = log.type ? log.type.charAt(0).toUpperCase() + log.type.slice(1) : 'Other';
                            
                            html += `
                                <div class="log-card ${logTypeClass}">
                                    <div class="log-header">
                                        <span class="log-time">${log.formatted_time}</span>
                                        <span class="log-type-badge ${logTypeClass}">${logType}</span>
                                    </div>
                                    <div class="log-body">
                                        <p class="mb-0">${formatLogMessage(log.message)}</p>
                                    </div>
                                </div>
                            `;
                        });
                        
                        logContainer.innerHTML = html;
                    } else {
                        logContainer.innerHTML = `
                            <div class="no-logs-message">
                                <i class="fas fa-info-circle me-2"></i>
                                No logs found for the selected filter and time period.
                            </div>
                        `;
                    }
                })
                .catch(error => {
                    console.error('Error loading logs:', error);
                    logContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="fas fa-exclamation-circle me-2"></i>
                            Error loading logs: ${error.message}
                        </div>
                    `;
                });
        }
        
        function formatLogMessage(message) {
            // Make links clickable
            message = message.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank">$1</a>');
            
            // Highlight keywords
            const keywords = ['tweet', 'post', 'liked', 'retweeted', 'commented', 'dm', 'found', 'error', 'exception'];
            keywords.forEach(keyword => {
                const regex = new RegExp(`\\b${keyword}\\b`, 'gi');
                message = message.replace(regex, '<strong>$&</strong>');
            });
            
            return message;
        }
        
        function startAutoRefresh() {
            stopAutoRefresh(); // Clear existing interval if any
            
            // Reset the countdown timer to either 15s or 60s depending on bot status
            updateRefreshTimer();
            
            refreshInterval = setInterval(() => {
                refreshCountdown--;
                updateRefreshTimer();
                
                if (refreshCountdown <= 0) {
                    // Check more frequently if bot is running
                    fetch('/bot_running')
                        .then(response => response.json())
                        .then(data => {
                            if (data.running) {
                                refreshCountdown = 15; // 15 seconds if bot is running
                            } else {
                                refreshCountdown = 60; // 60 seconds if bot is not running
                            }
                            loadLogs();
                        })
                        .catch(error => {
                            console.error('Error checking bot status:', error);
                            refreshCountdown = 60; // Default to 60 seconds if error
                            loadLogs();
                        });
                }
            }, 1000);
        }
        
        function stopAutoRefresh() {
            if (refreshInterval) {
                clearInterval(refreshInterval);
                refreshInterval = null;
            }
        }
        
        function updateRefreshTimer() {
            document.getElementById('refresh-timer').textContent = `${refreshCountdown}s`;
        }
    </script>
</body>
</html>
"""