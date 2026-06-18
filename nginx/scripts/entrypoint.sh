#!/bin/sh
set -e

# ============================================================================
# Nginx Entrypoint Script
# Handles environment variable substitution and SSL certificate setup
# ============================================================================

ENVIRONMENT="${ENVIRONMENT:-development}"
DOMAIN_NAME="${DOMAIN_NAME:-localhost}"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN_NAME}"

echo "Starting nginx with ENVIRONMENT=${ENVIRONMENT}, DOMAIN_NAME=${DOMAIN_NAME}"

# ============================================================================
# Function: Generate self-signed certificate
# ============================================================================
generate_self_signed_cert() {
    echo "Generating self-signed certificate for ${DOMAIN_NAME}..."
    mkdir -p "${CERT_PATH}"
    openssl req -x509 -nodes -newkey rsa:2048 \
        -days 1 \
        -keyout "${CERT_PATH}/privkey.pem" \
        -out "${CERT_PATH}/fullchain.pem" \
        -subj "/CN=${DOMAIN_NAME}"
    echo "Self-signed certificate generated."
}

# ============================================================================
# Function: Check if certificate exists and is valid
# ============================================================================
check_certificate() {
    if [ -f "${CERT_PATH}/fullchain.pem" ] && [ -f "${CERT_PATH}/privkey.pem" ]; then
        # Check if certificate is not expired
        if openssl x509 -checkend 86400 -noout -in "${CERT_PATH}/fullchain.pem" 2>/dev/null; then
            echo "Valid certificate found for ${DOMAIN_NAME}"
            return 0
        else
            echo "Certificate expired or expiring soon"
            return 1
        fi
    else
        echo "No certificate found for ${DOMAIN_NAME}"
        return 1
    fi
}

# ============================================================================
# Select and process configuration based on environment
# ============================================================================
case "${ENVIRONMENT}" in
    development|dev)
        echo "Using development configuration (HTTP only)"
        envsubst '${DOMAIN_NAME}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
        ;;

    staging)
        echo "Using staging configuration (HTTPS)"
        # Check/generate SSL certificate
        if ! check_certificate; then
            generate_self_signed_cert
        fi
        envsubst '${DOMAIN_NAME} ${CSP_CLERK_HOSTS}' < /etc/nginx/templates/staging.conf.template > /etc/nginx/conf.d/default.conf
        ;;

    production|prod)
        echo "Using production configuration (HTTPS)"
        # Check/generate SSL certificate
        if ! check_certificate; then
            generate_self_signed_cert
        fi
        envsubst '${DOMAIN_NAME} ${CSP_CLERK_HOSTS}' < /etc/nginx/templates/prod.conf.template > /etc/nginx/conf.d/default.conf
        ;;

    *)
        echo "Unknown environment: ${ENVIRONMENT}. Using development configuration."
        envsubst '${DOMAIN_NAME}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
        ;;
esac

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

echo "Starting nginx..."
exec "$@"
