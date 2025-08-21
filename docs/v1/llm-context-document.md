# OCPP 1.6 CSMS - LLM Context Document

## Overview for AI Assistants

This document provides context for Large Language Models (LLMs) like Claude to understand the current state and architecture of this OCPP 1.6 Charging Station Management System (CSMS) codebase.

---

## Project Summary

**What this system is**: A production-ready Electric Vehicle Charging Station Management System that implements OCPP 1.6 protocol for managing EV charging infrastructure with modern web technologies.

**Current Status**: Actively deployed on Render (backend) and Vercel (frontend) with Clerk authentication, handling real-world charging stations with WebSocket OCPP communication.

**Key Capabilities**: 
- Real-time OCPP 1.6 communication with charging stations
- Complete transaction lifecycle management with automated billing
- Role-based admin dashboard and user interfaces
- Interactive station maps and QR code scanning for users
- Remote charging control (start/stop, availability)
- Financial integration with wallet system and retry mechanisms

---

## Architecture at a Glance

```
EV Chargers (OCPP 1.6) ←→ FastAPI Backend (Python) ←→ Next.js Frontend (Admin + User)
                ↓                    ↓                           ↓
          WebSocket /ocpp/     PostgreSQL + Redis          Clerk Authentication
```

**Backend**: Python FastAPI with Tortoise ORM, Redis for connection state, Clerk JWT authentication  
**Frontend**: Next.js 15 with TypeScript, TanStack Query for state, role-based UI (Admin/User)  
**Database**: PostgreSQL with comprehensive schema for charging infrastructure  
**Protocol**: OCPP 1.6 via WebSocket with full message support  
**Authentication**: Clerk-powered JWT with role-based access control

---

## Critical File Locations

### Backend Core (`/backend/`)
- **`main.py`** - FastAPI app with OCPP WebSocket endpoint `/ocpp/{charge_point_id}` and all OCPP message handlers
- **`models.py`** - Complete database schema with OCPP enums, User, Charger, Transaction, Wallet models
- **`auth_middleware.py`** - Clerk JWT authentication with role-based access control (ADMIN/USER)
- **`redis_manager.py`** - Real-time connection state management for chargers
- **`tortoise_config.py`** - Database configuration with SSL for production

### API Routing (`/backend/routers/`)
- **`stations.py`** - Station CRUD with geographic data (`/api/admin/stations/*`)
- **`chargers.py`** - OCPP charger management with remote commands (`/api/admin/chargers/*`)
- **`transactions.py`** - Transaction tracking with meter values (`/api/admin/transactions/*`)
- **`users.py`** - User management with wallet operations (`/users/*`)
- **`webhooks.py`** - Clerk webhook processing for user lifecycle (`/webhooks/*`)

### Business Services (`/backend/services/`)
- **`wallet_service.py`** - Billing calculations and automated payment processing
- **`billing_retry_service.py`** - Background service for failed transaction recovery

### Frontend Core (`/frontend/`)
- **`app/page.tsx`** - Role-based dashboard (different for ADMIN vs USER)
- **`app/admin/`** - Complete admin interface for station/charger/user management
- **`app/stations/page.tsx`** - Interactive map with React Leaflet for station discovery
- **`app/scanner/page.tsx`** - QR code scanner using ZXing library
- **`middleware.ts`** - Route protection and role-based redirects
- **`components/RoleWrapper.tsx`** - RBAC components (AdminOnly, UserOnly, AuthenticatedOnly)

### API Integration (`/frontend/lib/`)
- **`api-client.ts`** - Base HTTP client with automatic Clerk JWT injection
- **`api-services.ts`** - Domain-specific services (stations, chargers, users, transactions)
- **`queries/`** - TanStack Query hooks with optimized caching strategies

### Key Configuration
- **`backend/requirements.txt`** - Python dependencies (FastAPI, python-ocpp, Tortoise ORM, etc.)
- **`frontend/package.json`** - Node dependencies (Next.js 15, React 19, Clerk, TanStack Query, etc.)
- **`backend/pyproject.toml`** - pytest configuration and Aerich migration settings

---

## Database Schema Quick Reference

### Core Tables with Relationships
```sql
-- User Management (Clerk Integration)
user (id, clerk_user_id, phone_number, full_name, role) -- USER/ADMIN roles
wallet (id, user_id, balance, currency)
wallet_transaction (id, wallet_id, amount, type)

-- Charging Infrastructure
charging_station (id, name, latitude, longitude, address)
charger (id, charge_point_string_id, station_id, vendor, model, latest_status, last_heart_beat_time)
connector (id, charger_id, connector_id, connector_type, max_power_kw)

-- OCPP Transactions  
transaction (id, user_id, charger_id, start_meter_kwh, end_meter_kwh, transaction_status)
meter_value (id, transaction_id, reading_kwh, current, voltage, power_kw)

-- System Logging
log (id, charge_point_id, direction, payload, correlation_id) -- All OCPP messages
```

### Important Enums
- **`ChargerStatusEnum`**: OCPP 1.6 statuses (Available, Charging, Unavailable, Faulted, etc.)
- **`TransactionStatusEnum`**: Complete lifecycle (RUNNING, COMPLETED, FAILED, BILLING_FAILED, etc.)
- **`UserRoleEnum`**: USER and ADMIN for role-based access control

---

## OCPP 1.6 Implementation Details

### Message Handlers in `main.py`

**Core OCPP Messages Implemented**:
1. **BootNotification** (`main.py:65-102`) - Charger registration, **❗ Known Issue**: fails ongoing transactions immediately
2. **Heartbeat** (`main.py:104-117`) - Connection liveness (90s timeout)  
3. **StatusNotification** (`main.py:119-140`) - Updates charger.latest_status
4. **StartTransaction** (`main.py:142-204`) - Creates Transaction with RUNNING status
5. **StopTransaction** (`main.py:206-261`) - Finalizes transaction with automated billing via WalletService
6. **MeterValues** (`main.py:263-387`) - Stores real-time energy data (kWh, current, voltage, power)

**Remote Commands Supported**:
- `RemoteStartTransaction` (`main.py:480-484`) - Start charging remotely
- `RemoteStopTransaction` (`main.py:485-489`) - Stop charging remotely  
- `ChangeAvailability` (`main.py:490-494`) - Set Operative/Inoperative

### WebSocket Endpoint
- **URL**: `ws://localhost:8000/ocpp/{charge_point_id}` (development)
- **Authentication**: Validates charge_point_string_id exists in database
- **Logging**: All messages logged to `log` table with correlation IDs
- **Connection Management**: Redis tracks active connections with heartbeat monitoring

---

## Authentication & Role-Based Access Control

### Clerk Integration
**Backend Authentication**: `auth_middleware.py` - ClerkJWTBearer for JWT validation
**Frontend Authentication**: `middleware.ts` - Route-level protection and role redirects
**User Roles**: USER (default) and ADMIN with automatic role assignment via webhooks

### RBAC Implementation
**Route Protection**:
- `/api/admin/*` - Requires ADMIN role
- `/users/*` - Requires authentication (any role)
- `/auth/*` - Public endpoints

**Component-Level RBAC**:
```typescript
// frontend/components/RoleWrapper.tsx
<AdminOnly>Admin-only content</AdminOnly>
<UserOnly>User-only content</UserOnly>  
<AuthenticatedOnly>Authenticated user content</AuthenticatedOnly>
```

### User Experience by Role
**USER Role**:
- Dashboard with quick access to station finder and QR scanner
- Interactive station map (`/stations`) with real-time availability
- QR code scanner (`/scanner`) for charger access
- Personal charging history and wallet balance

**ADMIN Role**:
- Full system dashboard with real-time statistics
- Station management (`/admin/stations`) with CRUD operations
- Charger management (`/admin/chargers`) with OCPP remote commands
- User management (`/admin/users`) with transaction history and wallet control

---

## API Endpoints Quick Reference

### Admin APIs (`/api/admin/`)
```
Stations:
GET/POST /stations - List/create stations with geographic data
GET/PUT/DELETE /stations/{id} - Individual station operations

Chargers:  
GET/POST /chargers - List/create chargers with real-time connection status
GET/PUT/DELETE /chargers/{id} - Individual charger operations
POST /chargers/{id}/remote-start - Send RemoteStartTransaction OCPP command
POST /chargers/{id}/remote-stop - Send RemoteStopTransaction OCPP command  
POST /chargers/{id}/change-availability - Send ChangeAvailability OCPP command

Transactions:
GET /transactions - List transactions with filtering and analytics summary
GET /transactions/{id} - Transaction details
GET /transactions/{id}/meter-values - Energy consumption data with chart data
```

### User APIs
```
GET /auth/profile - User profile with role information
GET /users - List users (admin only) or current user profile
GET /users/{id} - User details with transaction history and wallet info
```

### Legacy APIs (Backward Compatibility)
```
GET /api/charge-points - Connected charger list
POST /api/charge-points/{id}/request - Send OCPP command  
GET /api/logs - OCPP message logs
GET /api/logs/{charge_point_id} - Logs for specific charger
```

---

## Current State & Recent Architecture

### Technology Stack Updates
**Authentication**: Migrated from Supabase to Clerk for better JWT and role management
**Database**: Using Tortoise ORM (async) with PostgreSQL and SSL in production
**Frontend**: Next.js 15 with App Router, TypeScript, TanStack Query, Shadcn/ui
**Real-time**: Redis for connection state, TanStack Query polling for frontend updates

### Current Production Deployment  
- **Backend**: Render.com with environment variables for DB, Redis, Clerk credentials
- **Frontend**: Vercel with automatic deployments and CDN distribution
- **Database**: PostgreSQL with automated backups and SSL requirements
- **Monitoring**: Structured logging with correlation IDs, health check endpoints

### Known Working Features
✅ Complete OCPP 1.6 message handling with all core messages  
✅ Real-time charger status monitoring with Redis-backed connection tracking  
✅ Transaction lifecycle management with automated billing and retry logic  
✅ Remote start/stop charging with immediate OCPP command execution  
✅ Availability control for chargers (Operative/Inoperative)  
✅ Role-based admin dashboard with comprehensive management tools  
✅ User-friendly interfaces with interactive maps and QR scanning  
✅ Wallet system with automatic billing on transaction completion  
✅ Connection state tracking with automatic cleanup of dead connections  
✅ Comprehensive logging system for OCPP compliance and debugging  

---

## Code Patterns & Conventions

### Backend Patterns
```python
# OCPP message handlers use @on decorator
@on('StartTransaction')
async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
    # Business logic with user validation and vehicle profile creation
    return call_result.StartTransaction(transaction_id=id, id_tag_info={"status": "Accepted"})

# Database operations are async with relationships
charger = await Charger.filter(charge_point_string_id=cp_id).prefetch_related('station').first()
await charger.save()

# Redis connection state management  
await redis_manager.add_connected_charger(charger_id, connection_data)
is_connected = await redis_manager.is_charger_connected(charger_id)
```

### Frontend Patterns  
```typescript
// TanStack Query for data fetching with role-based optimization
const { data: chargers } = useChargers({ refetchInterval: 10000 }); // Admin real-time
const { data: stations } = useStations({ staleTime: 2 * 60 * 1000 }); // User longer cache

// Role-based component rendering
const Dashboard = () => {
  const { user } = useUser();
  const isAdmin = user?.publicMetadata?.role === 'ADMIN';
  
  return isAdmin ? <AdminDashboard /> : <UserDashboard />;
};

// Optimistic updates with rollback
const mutation = useMutation({
  onMutate: (variables) => {
    queryClient.setQueryData(['chargers'], optimisticUpdate);
  },
  onError: (error, variables, context) => {
    queryClient.setQueryData(['chargers'], context.previousData);
  }
});
```

---

## Development Environment Setup

### Backend Setup
```bash
cd backend
# IMPORTANT: Always activate the virtual environment first
source .venv/bin/activate
pip install -r requirements.txt
# Set environment variables: DATABASE_URL, REDIS_URL, CLERK_* credentials
python main.py  # Starts on port 8000 with OCPP WebSocket endpoint
```

**Note for AI Assistants**: Always activate the virtual environment with `source .venv/bin/activate` before running any Python commands in the backend directory. The project uses a virtual environment located at `backend/.venv/`.

### Frontend Setup  
```bash
cd frontend
npm install
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
# Set NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY
npm run dev  # Starts on port 3000 with role-based routing
```

### Database Migrations
```bash
cd backend
source .venv/bin/activate
aerich migrate --name "description"  # Generate migration
aerich upgrade  # Apply migration to database
```

---

## Testing Framework

### Test Categories  
```bash
pytest -m unit          # Fast tests (~1 second) - models, API endpoints
pytest -m integration   # Full OCPP WebSocket tests (~45 seconds) - complete charging sessions
pytest -m infrastructure # Database/Redis tests (~5 seconds) - external dependencies
```

### OCPP Simulators
- **`simulators/ocpp_simulator_full_success.py`** - Complete charging session simulation
- **`simulators/ocpp_simulator_change_availability.py`** - Availability command testing

### Test Environment
- **Configuration**: `backend/pyproject.toml` with async support and markers
- **Fixtures**: `backend/tests/conftest.py` with database setup and cleanup
- **Coverage**: Available with `pytest --cov=. --cov-report=html`

---

## Technical Debt & Known Issues

### Critical Issue: Boot Notification Transaction Handling
**Location**: `backend/main.py:69-94`  
**Problem**: BootNotification handler immediately fails all ongoing transactions with status FAILED  
**Impact**: Users lose active charging sessions when chargers reboot  
**Solution Required**: Implement transaction reconciliation with PENDING_RECONCILIATION status  

### Performance Optimization Opportunities
1. **N+1 Queries**: Some charger list operations could use bulk Redis operations
2. **Frontend Bundle**: ~2MB bundle could be reduced 30-40% with admin-only code splitting
3. **Database Queries**: Could benefit from additional indexing for OCPP operations

### Security Enhancements Needed
1. **OCPP Message Validation**: Limited schema validation for incoming OCPP messages
2. **Rate Limiting**: No rate limiting implemented for API endpoints
3. **Audit Logging**: Could enhance security event logging beyond OCPP messages

---

## Common Development Tasks

### Adding a New OCPP Message Handler
1. Add handler method with `@on('MessageName')` decorator in `main.py`
2. Update database schema if needed (create migration with `aerich migrate`)
3. Add frontend API integration if user-facing (update `api-services.ts`)
4. Write integration tests in `tests/test_integration.py`

### Adding a New API Endpoint
1. Add route to appropriate router (`routers/stations.py`, `routers/chargers.py`, etc.)
2. Add CRUD functions if database operations needed
3. Add frontend service function in `lib/api-services.ts`  
4. Create TanStack Query hook in `lib/queries/`
5. Update TypeScript types in `types/api.ts`

### Debugging OCPP Issues
1. Check `log` table for all OCPP messages with correlation IDs
2. Verify charger exists in database with correct `charge_point_string_id`  
3. Check Redis connection state: `await redis_manager.is_charger_connected(cp_id)`
4. Monitor heartbeat: check `last_heart_beat_time` in charger table
5. Use OCPP simulators for controlled testing

### Role-Based Feature Development
1. **Backend**: Use `RequireAdmin` or `RequireAuth` dependencies in route handlers
2. **Frontend**: Wrap components in `<AdminOnly>`, `<UserOnly>`, or `<AuthenticatedOnly>`
3. **API Services**: Ensure proper error handling for 403 Forbidden responses
4. **Testing**: Test both admin and user access patterns

---

## Important Constraints & Considerations

### OCPP Compliance
- Must maintain OCPP 1.6 message format exactly
- All timestamps in ISO 8601 format with 'Z' suffix  
- Energy values: Convert Wh to kWh (divide by 1000) for database storage
- Status values must match OCPP 1.6 enum exactly
- Complete audit trail required for certification

### Performance Considerations
- Redis used for connection state (fast O(1) lookups)
- Database connections pooled (max 20 connections)
- Frontend polling every 10 seconds (optimized by role and data type)
- Bulk operations for admin dashboard efficiency  
- TanStack Query caching optimized by data volatility

### Data Integrity & Business Logic
- `charge_point_string_id` must be unique across chargers
- Transactions linked to users via RFID card ID lookup
- OCPP message logging essential for compliance/debugging
- Automatic billing on transaction completion with retry mechanism
- Connection cleanup prevents resource leaks

---

## Security & Production Notes

### Current Security
- CORS configured for specific origins (development and production)
- Database credentials via environment variables
- Clerk-based JWT authentication with role validation
- OCPP WebSocket validates charger registration before connection
- SSL required for production database connections

### Production Configuration
- PostgreSQL with SSL required connections
- Redis connection URL from environment variables
- Clerk webhook signature validation for user lifecycle events
- Frontend API URL configurable via environment
- Structured logging with correlation IDs for audit trail

---

## Key Files for LLM Understanding

**If you need to understand the codebase, start with these files in order**:

1. **`backend/main.py`** - Core OCPP WebSocket handling, all message handlers, FastAPI app setup
2. **`backend/models.py`** - Complete database schema with relationships and OCPP-compliant enums
3. **`frontend/app/page.tsx`** - Role-based dashboard to understand user experience patterns
4. **`backend/routers/chargers.py`** - Most complex API with OCPP integration and admin operations
5. **`frontend/components/RoleWrapper.tsx`** - RBAC implementation patterns
6. **`backend/auth_middleware.py`** - Clerk authentication and role validation
7. **`frontend/lib/api-client.ts`** - Frontend-backend integration with automatic JWT handling

**For specific functionality**:
- **OCPP message handling** → `main.py` (ChargePoint class with @on decorators)  
- **Database schema & relationships** → `models.py`
- **Admin APIs & OCPP commands** → `routers/` directory
- **User interfaces & role-based UI** → `frontend/app/` directory  
- **Real-time features & caching** → `redis_manager.py` + `lib/queries/` hooks
- **Authentication & RBAC** → `auth_middleware.py` + `middleware.ts` + `RoleWrapper.tsx`
- **Financial operations** → `services/wallet_service.py` + `services/billing_retry_service.py`

**For troubleshooting**:
- **OCPP communication issues** → Check `log` table and `redis_manager.py` connection state
- **Authentication problems** → Check Clerk webhook processing in `routers/webhooks.py`
- **Transaction billing issues** → Check `wallet_service.py` and BILLING_FAILED status handling
- **Frontend role issues** → Check `middleware.ts` and role-based component wrappers

This context should give any LLM a solid foundation for understanding and working with this modern, production-ready OCPP 1.6 CSMS with role-based access control and comprehensive user experience features.