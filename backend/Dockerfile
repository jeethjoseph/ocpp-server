# ============================================
# Stage 1: Base image with Python dependencies
# ============================================
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies required for asyncpg and other packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Stage 2: Builder - Install Python dependencies
# ============================================
FROM base AS builder

COPY requirements.txt .
RUN pip install --user -r requirements.txt

# ============================================
# Stage 3: Development image
# ============================================
FROM base AS development

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Create firmware_files directory
RUN mkdir -p /app/firmware_files

# Development uses volume mounts for code
# CMD runs uvicorn with reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ============================================
# Stage 4: Production image
# ============================================
FROM base AS production

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY . .

# Create firmware_files directory if not exists
RUN mkdir -p /app/firmware_files

# Make entrypoint scripts executable
RUN chmod +x docker-entrypoint.sh start_server.sh 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Use docker-entrypoint.sh which runs migrations then starts the app
ENTRYPOINT ["./docker-entrypoint.sh"]
