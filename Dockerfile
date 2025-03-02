# Use a specific Python version for reproducibility
FROM python:3.10.12-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy and install requirements separately for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Start a new stage for a smaller final image
FROM python:3.10.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install curl for health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user to run the application
RUN groupadd -r twitterbot && useradd -r -g twitterbot twitterbot

# Set the working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application code
COPY --chown=twitterbot:twitterbot . .

# Create necessary directories with proper permissions
RUN mkdir -p /app/logs /app/downloads /app/local_test_data /app/uploads/temp && \
    chown -R twitterbot:twitterbot /app/logs /app/downloads /app/local_test_data /app/uploads

# Add health check endpoint placeholder for dashboard.py
RUN if ! grep -q "def health" src/dashboard.py; then \
    echo -e "\n@app.route('/health')\ndef health():\n    return jsonify({'status': 'healthy'}), 200" >> src/dashboard.py; \
    fi

# Expose the port
EXPOSE 5003

# Create a health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5003/health || exit 1

# Switch to the non-root user
USER twitterbot

# Set up entrypoint script
COPY --chown=twitterbot:twitterbot docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Start the application
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5003", "--workers", "2", "--timeout", "120", "src.dashboard:app"]