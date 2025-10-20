# Dockerfile for Honeyspeak Flask app
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY scripts/ ./scripts/

# Create logs directory and default storage directory
RUN mkdir -p /app/logs /data/honeyspeak/assets_hires /data/honeyspeak/assets

# Set Python path to find libs module
ENV PYTHONPATH=/app/scripts:$PYTHONPATH

# Set default storage paths
ENV STORAGE_HOME=/data
ENV STORAGE_DIRECTORY=/data/honeyspeak

# Expose Flask port
EXPOSE 5002

# Entrypoint
CMD ["python", "scripts/app.py"]
