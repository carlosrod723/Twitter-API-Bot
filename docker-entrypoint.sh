#!/bin/bash
set -e

# Create necessary directories if they don't exist
mkdir -p /app/logs /app/downloads /app/uploads/temp

# Check for AWS environment
if [ -n "$AWS_EXECUTION_ENV" ] || [ -n "$AWS_LAMBDA_FUNCTION_NAME" ] || [ -n "$AWS_REGION" ]; then
    echo "Running in AWS environment..."
    
    # Set up AWS logging configuration
    export LOG_LEVEL=${LOG_LEVEL:-INFO}
    
    # Check for OAuth token
    if [ -n "$OAUTH_2_REFRESH_TOKEN" ]; then
        echo "OAuth token found, checking validity..."
        python -m src.regenerate_oauth2_token --check
    else
        echo "Warning: No OAuth token found. Please obtain a token using the OAuth flow."
    fi
    
    # Verify AWS credentials are available
    if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ]; then
        echo "AWS credentials found..."
    else
        echo "Warning: AWS credentials not found. S3 and DynamoDB features may not work."
    fi
fi

# Run database initialization if needed
if [ -n "$INIT_DB" ] && [ "$INIT_DB" = "true" ]; then
    echo "Initializing database tables..."
    python -c "from src.dynamodb_integration import create_tables_if_not_exist; create_tables_if_not_exist()"
fi

# Run content refresh if needed
if [ -n "$REFRESH_CONTENT" ] && [ "$REFRESH_CONTENT" = "true" ]; then
    echo "Refreshing content cache..."
    python -c "from src.content_manager import ContentManager; cm = ContentManager(); cm._refresh_local_content(); cm._refresh_s3_content() if cm.has_s3 else None"
fi

# Add a health endpoint to the Flask app
if [ -f "src/dashboard.py" ]; then
    if ! grep -q "@app.route('/health')" src/dashboard.py; then
        echo "Adding health endpoint to dashboard..."
        cat >> src/dashboard.py << 'EOF'
@app.route('/health')
def health():
    """Health check endpoint for container orchestration."""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat(), "service": "twitter-bot-dashboard"})
EOF
    fi
fi

# Check if specific service is needed
if [ "$1" = "--oauth" ]; then
    echo "Starting OAuth authorization flow..."
    exec python -m src.main --oauth
elif [ "$1" = "--bot" ]; then
    echo "Starting Twitter bot main process..."
    exec python -m src.main
elif [ "$1" = "--refresh-token" ]; then
    echo "Refreshing OAuth token..."
    python -m src.regenerate_oauth2_token
    # Continue to run the dashboard after token refresh
    shift
    exec "$@"
elif [ "$1" = "--dashboard" ]; then
    echo "Starting dashboard only..."
    shift
    exec "$@"
else
    # Execute the command passed to docker
    echo "Executing command: $@"
    exec "$@"
fi