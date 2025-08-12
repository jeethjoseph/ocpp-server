# OCPP 1.6 CSMS - LLM Context Document

## Overview for AI Assistants

This document provides context for Large Language Models (LLMs) like Claude to understand the current state and architecture of this OCPP 1.6 Charging Station Management System (CSMS) codebase.

---

## Project Summary

**What this system is**: A production-ready Electric Vehicle Charging Station Management System that implements OCPP 1.6 protocol for managing EV charging infrastructure.

**Current Status**: Actively deployed on Render with a React admin dashboard, handling real-world charging stations with WebSocket OCPP communication.

**Key Capabilities**: 
- Real-time OCPP 1.6 communication with charging stations
- Complete transaction lifecycle management
- Admin dashboard for station/charger management  
- Remote charging control (start/stop, availability)
- Financial integration with wallet system

---

## Architecture at a Glance

```
EV Chargers (OCPP 1.6) ←→ FastAPI Backend (Python) ←→ Next.js Admin Dashboard
                ↓                    ↓
          WebSocket /ocpp/     PostgreSQL + Redis
```

**Backend**: Python FastAPI with Tortoise ORM, Redis for connection state  
**Frontend**: Next.js 15 with TypeScript, TanStack Query for state management  
**Database**: PostgreSQL with comprehensive schema for charging infrastructure  
**Protocol**: OCPP 1.6 via WebSocket with full message support  

---

## Critical File Locations

### Backend Core (`/backend/`)
- `main.py` - **FastAPI app with OCPP WebSocket endpoint** `/ocpp/{charge_point_id}`
- `models.py` - **Complete database schema** with OCPP enums and relationships
- `crud.py` - **Database operations** for OCPP functionality  
- `redis_manager.py` - **Connection state management**
- `routers/` - **REST API endpoints** (stations, chargers, transactions)

### Frontend Core (`/frontend/`)
- `app/page.tsx` - **Main dashboard** with real-time stats
- `app/chargers/page.tsx` - **Charger management** with OCPP status monitoring
- `lib/api-client.ts` - **HTTP client** for backend integration
- `lib/queries/` - **TanStack Query hooks** for data fetching

### Key Configuration
- `backend/tortoise_config.py` - Database configuration
- `backend/requirements.txt` - Python dependencies (FastAPI, python-ocpp, etc.)
- `frontend/package.json` - Node dependencies (Next.js 15, React 19, etc.)

---

## Database Schema Quick Reference

### Core Tables
```sql
-- Charging infrastructure
charging_station (id, name, latitude, longitude, address)
charger (id, charge_point_string_id, station_id, vendor, model, latest_status)
connector (id, charger_id, connector_id, connector_type, max_power_kw)

-- OCPP transactions  
transaction (id, user_id, charger_id, start_meter_kwh, end_meter_kwh, transaction_status)
meter_value (id, transaction_id, reading_kwh, current, voltage, power_kw)

-- System logging
log (id, charge_point_id, direction, payload, correlation_id) -- All OCPP messages

-- Financial
user (id, phone_number, full_name)
wallet (id, user_id, balance)
wallet_transaction (id, wallet_id, amount, type, charging_transaction_id)
```

### Important Enums
- `ChargerStatusEnum`: OCPP 1.6 statuses (Available, Charging, Unavailable, Faulted, etc.)
- `TransactionStatusEnum`: Transaction lifecycle (RUNNING, COMPLETED, FAILED, etc.)

---

## OCPP 1.6 Implementation Details

### Message Handlers in `main.py`

**Core OCPP Messages Implemented**:
1. **BootNotification** - Charger registration, cleans up stale transactions
2. **Heartbeat** - Connection liveness (90s timeout)  
3. **StatusNotification** - Updates charger.latest_status
4. **StartTransaction** - Creates Transaction with RUNNING status
5. **StopTransaction** - Finalizes transaction, calculates energy consumption
6. **MeterValues** - Stores real-time energy data (kWh, current, voltage, power)

**Remote Commands Supported**:
- `RemoteStartTransaction` - Start charging remotely
- `RemoteStopTransaction` - Stop charging remotely
- `ChangeAvailability` - Set Operative/Inoperative

### WebSocket Endpoint
- **URL**: `ws://localhost:8000/ocpp/{charge_point_id}`
- **Authentication**: Validates charge_point_string_id exists in database
- **Logging**: All messages logged to `log` table with correlation IDs
- **Connection Management**: Redis tracks active connections

---

## API Endpoints Quick Reference

### Admin APIs (`/api/admin/`)
```
Stations:
GET/POST /stations - List/create stations
GET/PUT/DELETE /stations/{id} - Individual station operations

Chargers:
GET/POST /chargers - List/create chargers  
GET/PUT/DELETE /chargers/{id} - Individual charger operations
POST /chargers/{id}/remote-start - Send RemoteStartTransaction
POST /chargers/{id}/remote-stop - Send RemoteStopTransaction
POST /chargers/{id}/change-availability - Send ChangeAvailability

Transactions:
GET /transactions - List transactions with filtering
GET /transactions/{id} - Transaction details
GET /transactions/{id}/meter-values - Energy consumption data
```

### Legacy APIs (Backward Compatibility)
```
GET /api/charge-points - Connected charger list
POST /api/charge-points/{id}/request - Send OCPP command
GET /api/logs - OCPP message logs
```

---

## Current State & Recent Changes

### Recent Migration (Git Branch: 1-rewrite-the-server-with-tortoise-orm)
- **Database**: Migrated from SQLAlchemy to Tortoise ORM (async)
- **Status**: Production-ready, all core OCPP functionality working
- **Latest Changes**: Transaction management improvements, bootnotification transaction cleanup

### Known Working Features
✅ Complete OCPP 1.6 message handling  
✅ Real-time charger status monitoring  
✅ Transaction lifecycle management  
✅ Remote start/stop charging  
✅ Availability control  
✅ Admin dashboard with live updates  
✅ Connection state tracking with Redis  
✅ Comprehensive logging system  

### Current Deployment
- **Backend**: Render.com with PostgreSQL and Redis
- **Frontend**: Likely Vercel (configured for production)
- **CORS**: Configured for `https://ocpp-frontend-mu.vercel.app`

---

## Code Patterns & Conventions

### Backend Patterns
```python
# OCPP message handlers use @on decorator
@on('StartTransaction')
async def on_start_transaction(self, connector_id, id_tag, meter_start, **kwargs):
    # Business logic
    return call_result.StartTransaction(transaction_id=id, id_tag_info={"status": "Accepted"})

# Database operations are async
charger = await Charger.filter(charge_point_string_id=cp_id).first()
await charger.save()

# Redis connection state
await redis_manager.add_connected_charger(charger_id, connection_data)
```

### Frontend Patterns  
```typescript
// TanStack Query for data fetching
const { data: chargers } = useChargers({ refetchInterval: 10000 });

// Optimistic updates for immediate UI feedback
const mutation = useMutation({
  onMutate: (variables) => {
    // Update cache immediately
    queryClient.setQueryData(['chargers'], optimisticUpdate);
  }
});
```

---

## Development Environment Setup

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
# Set environment variables: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, REDIS_URL
python main.py  # Starts on port 8000
```

### Frontend Setup  
```bash
cd frontend
npm install
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev  # Starts on port 3000
```

### Database Migrations
```bash
cd backend
aerich migrate --name "description"  # Generate migration
aerich upgrade  # Apply migration
```

---

## Testing Framework

### Test Categories
```bash
pytest -m unit          # Fast tests (~1 second)
pytest -m integration   # Full OCPP WebSocket tests (~45 seconds)  
pytest -m infrastructure # Database/Redis tests (~5 seconds)
```

### OCPP Simulators
- `simulators/ocpp_simulator_full_success.py` - Complete charging session simulation
- `simulators/ocpp_simulator_change_availability.py` - Availability command testing

---

## Common Development Tasks

### Adding a New OCPP Message Handler
1. Add handler method with `@on('MessageName')` decorator in `main.py`
2. Update database schema if needed (add migration)
3. Add frontend API integration if user-facing
4. Write integration tests

### Adding a New API Endpoint
1. Add route to appropriate router (`routers/stations.py`, `routers/chargers.py`, etc.)
2. Add CRUD functions to `crud.py` if database operations needed
3. Add frontend service function and React Query hook
4. Update TypeScript types in `frontend/types/api.ts`

### Debugging OCPP Issues
1. Check `log` table for all OCPP messages with correlation IDs
2. Verify charger exists in database with correct `charge_point_string_id`  
3. Check Redis connection state: `await redis_manager.is_charger_connected(cp_id)`
4. Monitor heartbeat: check `last_heart_beat_time` in charger table

---

## Important Constraints & Considerations

### OCPP Compliance
- Must maintain OCPP 1.6 message format exactly
- All timestamps in ISO 8601 format with 'Z' suffix
- Energy values: Convert Wh to kWh (divide by 1000)
- Status values must match OCPP 1.6 enum exactly

### Performance Considerations
- Redis used for connection state (fast O(1) lookups)
- Database connections pooled (max 20 connections)
- Frontend polling every 10 seconds (not WebSocket to frontend)
- Bulk operations for dashboard efficiency

### Data Integrity
- `charge_point_string_id` must be unique across chargers
- Transactions linked to users, chargers, and vehicles
- OCPP message logging essential for compliance/debugging
- Connection cleanup prevents resource leaks

---

## Security & Production Notes

### Current Security
- CORS configured for specific origins
- Database credentials via environment variables
- No authentication on admin APIs (internal use)
- OCPP WebSocket validates charger registration

### Production Configuration
- PostgreSQL with SSL required
- Redis connection URL from environment
- Frontend API URL configurable
- Structured logging with correlation IDs

---

## Key Files for LLM Understanding

**If you need to understand the codebase, start with these files in order**:

1. `backend/main.py` - Core OCPP WebSocket handling and FastAPI app
2. `backend/models.py` - Complete database schema and relationships
3. `frontend/app/page.tsx` - Main dashboard to understand UI
4. `backend/routers/chargers.py` - Most complex API with OCPP integration
5. `frontend/lib/api-client.ts` - Frontend-backend integration
6. `backend/crud.py` - Database operations

**For specific functionality**:
- OCPP message handling → `main.py` (ChargePoint class)
- Database schema → `models.py` 
- API endpoints → `routers/` directory
- Frontend components → `frontend/app/` directory
- Real-time features → `redis_manager.py` + TanStack Query hooks

This context should give any LLM a solid foundation for understanding and working with this OCPP 1.6 CSMS codebase.