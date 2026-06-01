# ============================================
# Stage 1: Dependencies
# ============================================
FROM node:20-alpine AS deps

WORKDIR /app

# Install dependencies needed for native modules
RUN apk add --no-cache libc6-compat

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# ============================================
# Stage 2: Builder
# ============================================
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time environment variables (NEXT_PUBLIC_* must be set at build time)
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY
ARG NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID
ARG NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID
ARG NEXT_PUBLIC_NEW_RELIC_TRUST_KEY
ARG NEXT_PUBLIC_NEW_RELIC_AGENT_ID
# Sentry: NEXT_PUBLIC_SENTRY_DSN is baked into the client bundle. SENTRY_ORG /
# SENTRY_PROJECT / SENTRY_AUTH_TOKEN are consumed by `withSentryConfig` during
# the build for source-map upload only — they never need to be ENV-promoted
# and AUTH_TOKEN must not be persisted into any image layer.
ARG NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_SENTRY_ENVIRONMENT
ARG SENTRY_ORG
ARG SENTRY_PROJECT
ARG SENTRY_AUTH_TOKEN

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV NEXT_PUBLIC_APP_URL=$NEXT_PUBLIC_APP_URL
ENV NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY=$NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY
ENV NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID=$NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID
ENV NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID=$NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID
ENV NEXT_PUBLIC_NEW_RELIC_TRUST_KEY=$NEXT_PUBLIC_NEW_RELIC_TRUST_KEY
ENV NEXT_PUBLIC_NEW_RELIC_AGENT_ID=$NEXT_PUBLIC_NEW_RELIC_AGENT_ID
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_SENTRY_ENVIRONMENT=$NEXT_PUBLIC_SENTRY_ENVIRONMENT

# Build the application. SENTRY_* vars injected inline so AUTH_TOKEN
# (secret) is not retained in any later image layer; ORG/PROJECT inlined
# alongside for consistency.
RUN SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN \
    SENTRY_ORG=$SENTRY_ORG \
    SENTRY_PROJECT=$SENTRY_PROJECT \
    npm run build

# ============================================
# Stage 3: Development
# ============================================
FROM node:20-alpine AS development

WORKDIR /app

# Install dependencies needed for native modules
RUN apk add --no-cache libc6-compat

# Copy package files
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies)
RUN npm ci

# Development uses volume mounts for code
# CMD runs next dev
CMD ["npm", "run", "dev"]

# ============================================
# Stage 4: Production Runner
# ============================================
FROM node:20-alpine AS production

WORKDIR /app

ENV NODE_ENV=production

# Add non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy necessary files from builder
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Set correct permissions
RUN chown -R nextjs:nodejs /app

USER nextjs

# Health check — hits a public liveness route (see app/api/health/route.ts).
# Earlier versions probed `/` which is Clerk-protected and returns 404 for
# unauthenticated probes, marking healthy containers as unhealthy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/health || exit 1

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
