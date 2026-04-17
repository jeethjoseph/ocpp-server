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

# Install system dependencies required for asyncpg and other packages.
# gosu is used by the production entrypoint to drop privileges from root to the
# app user after fixing ownership on mounted volumes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    gosu \
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

# Create non-root user early so we can chown copied files
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home --shell /sbin/nologin app

# Copy dependencies from builder into the non-root user's home
COPY --from=builder --chown=app:app /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH

# Copy application code with correct ownership
COPY --chown=app:app . .

# Create firmware_files directory (writable by app user)
RUN mkdir -p /app/firmware_files && chown -R app:app /app

# Make entrypoint scripts executable
RUN chmod +x docker-entrypoint.sh start_server.sh 2>/dev/null || true

# NOTE: no USER directive here. docker-entrypoint.sh starts as root, fixes
# ownership on /app/firmware_files (heals pre-existing volumes whose root
# directory was created under a different user), then re-execs itself under the
# app user via gosu. The rest of the script — migrations, uvicorn — runs
# unprivileged.

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Use docker-entrypoint.sh which runs migrations then starts the app
ENTRYPOINT ["./docker-entrypoint.sh"]
