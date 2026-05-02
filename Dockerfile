# Multi-stage build for LangRAG Application
# Stage 1: Build React frontend
FROM node:18-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend package files
COPY ui/frontend/package*.json ./

# Install frontend dependencies
RUN npm ci --silent

# Copy frontend source
COPY ui/frontend/ ./

# Build optimized production bundle
ARG REACT_APP_API_BASE_URL=""
ENV REACT_APP_API_BASE_URL=$REACT_APP_API_BASE_URL
RUN npm run build

# Stage 2: Python backend with frontend static files
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    nginx \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Note: libpq-dev is included for psycopg2 (in pyproject.toml dependencies)
# When migrating to database in the future, this will already be available

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Copy pyproject.toml for dependency installation
COPY pyproject.toml .

# Install Python dependencies from pyproject.toml
# Using --no-build-isolation to avoid rebuilding setuptools
RUN uv pip install --system --no-build-isolation .

# Copy backend application code
COPY src/ ./src/

# Copy built frontend from previous stage
COPY --from=frontend-builder /app/frontend/build /app/frontend/build

# Create necessary directories with proper permissions
RUN mkdir -p /app/examples /app/logs /app/output /app/secrets /app/data/podcasts

# Copy nginx configuration (main + shared proxy snippet).
# The HTTPS server blocks ship to /app for the operator to copy into
# /etc/nginx/conf.d/ during the first-time TLS issuance (see deploy runbook),
# so local dev with no certs never tries to load missing keys.
COPY nginx.conf /etc/nginx/nginx.conf
COPY proxy_rag.conf /etc/nginx/proxy_rag.conf
COPY nginx-https.conf /app/nginx-https.conf

# Set PYTHONPATH for imports from src/ and project root (for matrix_decryption)
ENV PYTHONPATH=/app/src:/app:$PYTHONPATH

# Create non-root user that matches host user (UID/GID will be passed as build args)
ARG USER_ID=1001
ARG GROUP_ID=1001
RUN groupadd -g ${GROUP_ID} appuser || true && \
    useradd -u ${USER_ID} -g ${GROUP_ID} -m -s /bin/bash appuser || true

# Change ownership of app directory and nginx directories
RUN chown -R appuser:appuser /app && \
    chown -R appuser:appuser /var/log/nginx && \
    chown -R appuser:appuser /var/lib/nginx && \
    touch /var/run/nginx.pid && \
    chown appuser:appuser /var/run/nginx.pid

# Switch to non-root user
USER appuser

# Expose ports
EXPOSE 80 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start nginx (background) and uvicorn (foreground)
CMD ["sh", "-c", "nginx && exec uvicorn src.main:app --host 0.0.0.0 --port 8000"]
