# Stage 1: Build WebUI
FROM node:20-slim AS webui-builder
WORKDIR /app/webui
COPY webui/package*.json ./
RUN npm install
COPY webui/ ./
RUN npm run build

# Stage 2: Runtime
FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8000

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    build-essential \
    libavdevice-dev \
    libavfilter-dev \
    libopus-dev \
    libvpx-dev \
    pkg-config \
    libsrtp2-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy project configuration files
COPY pyproject.toml .
COPY src/printguard/requirements.txt src/printguard/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy built WebUI from Stage 1
COPY --from=webui-builder /app/webui/dist ./webui/dist

# Copy the rest of the application
COPY . .

# Install the project in editable mode or just ensure scripts are installed
RUN pip install --no-cache-dir .

# Copy and set up entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose the port the app runs on
EXPOSE $PORT

# Command to run the application
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["printguard", "serve"]
