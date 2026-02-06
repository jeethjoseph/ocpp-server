# Nginx Dockerfile for OCPP Server
FROM nginx:1.25-alpine

# Install openssl for self-signed cert generation and envsubst for variable substitution
RUN apk add --no-cache openssl gettext

# Create directories
RUN mkdir -p /var/www/certbot /etc/nginx/templates

# Copy entrypoint script
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy configuration files as templates
COPY default.conf /etc/nginx/templates/default.conf.template
COPY staging.conf /etc/nginx/templates/staging.conf.template
COPY prod.conf /etc/nginx/templates/prod.conf.template

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
