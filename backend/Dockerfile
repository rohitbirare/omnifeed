FROM python:3.11-slim

# Install system dependencies: FFmpeg and Unicode/Devanagari fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-dejavu \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data/media

# Default environment variables
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DATA_DIR=/app/data

EXPOSE 8000

# Start Uvicorn reading PORT dynamically from the environment
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST} --port ${PORT}"]
