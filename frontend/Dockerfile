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
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY
ARG NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID
ARG NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID
ARG NEXT_PUBLIC_NEW_RELIC_TRUST_KEY
ARG NEXT_PUBLIC_NEW_RELIC_AGENT_ID

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
ENV NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY=$NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY
ENV NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID=$NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID
ENV NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID=$NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID
ENV NEXT_PUBLIC_NEW_RELIC_TRUST_KEY=$NEXT_PUBLIC_NEW_RELIC_TRUST_KEY
ENV NEXT_PUBLIC_NEW_RELIC_AGENT_ID=$NEXT_PUBLIC_NEW_RELIC_AGENT_ID

# Build the application
RUN npm run build

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

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
