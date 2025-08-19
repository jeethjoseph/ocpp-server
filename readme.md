# OCPP Charging Station Management System

A comprehensive, production-ready EV charging station management system implementing OCPP 1.6 protocol with modern web technologies. This system provides real-time monitoring, control, and management of electric vehicle charging infrastructure with role-based access control and integrated financial management.

## 🏗️ Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        OCPP CSMS Architecture                    │
├─────────────────────────┬───────────────────────────────────────┤
│                        │                                       │
│      Frontend          │             Backend                   │
│    (Next.js 15)        │           (FastAPI)                   │
│                        │                                       │
│  ┌─────────────────┐   │   ┌─────────────────────────────────┐ │
│  │  Web Dashboard  │◄──┼──►│     REST API Server             │ │
│  │                 │   │   │                                 │ │
│  │ • Admin UI      │   │   │ • Station Management            │ │
│  │ • User UI       │   │   │ • Charger Control               │ │
│  │ • Interactive   │   │   │ • Transaction Tracking          │ │
│  │   Maps          │   │   │ • User Management               │ │
│  │ • QR Scanner    │   │   │ • Wallet Operations             │ │
│  └─────────────────┘   │   └─────────────────────────────────┘ │
│                        │              │                        │
│  ┌─────────────────┐   │   ┌─────────────────────────────────┐ │
│  │   Clerk Auth    │◄──┼──►│    OCPP WebSocket Server        │ │
│  │                 │   │   │                                 │ │
│  │ • JWT Tokens    │   │   │ • OCPP 1.6 Protocol            │ │
│  │ • RBAC          │   │   │ • Real-time Communication       │ │
│  │ • User Sessions │   │   │ • Connection Management         │ │
│  └─────────────────┘   │   └─────────────────────────────────┘ │
│                        │              │                        │
└─────────────────────────┼──────────────┼────────────────────────┘
                         │              │
           ┌─────────────────────────────────────────┐
           │              Database Layer             │
           │                                         │
           │  ┌─────────────┐    ┌─────────────────┐  │
           │  │ PostgreSQL  │    │     Redis       │  │
           │  │             │    │                 │  │
           │  │ • Stations  │    │ • Connections   │  │
           │  │ • Chargers  │    │ • Sessions      │  │
           │  │ • Txns      │    │ • Real-time     │  │
           │  │ • Users     │    │   State         │  │
           │  │ • Wallets   │    │ • Cache         │  │
           │  └─────────────┘    └─────────────────┘  │
           └─────────────────────────────────────────┘
                         │
           ┌─────────────────────────────────────────┐
           │            OCPP Charge Points           │
           │                                         │
           │  📱─────  📱─────  📱─────  📱─────     │
           │  │ CP-1│  │ CP-2│  │ CP-3│  │ CP-N│     │
           │  │     │  │     │  │     │  │     │     │
           │  └─────┘  └─────┘  └─────┘  └─────┘     │
           └─────────────────────────────────────────┘
```

## 🛠️ Technology Stack

### Backend (Python FastAPI)
- **Framework**: FastAPI with Uvicorn ASGI server
- **Database**: PostgreSQL with Tortoise ORM (async)
- **Cache**: Redis for connection state management
- **Authentication**: Clerk JWT validation with role-based access
- **Protocol**: OCPP 1.6 WebSocket implementation
- **API**: RESTful APIs with OpenAPI documentation
- **Deployment**: Production-ready on Render

### Frontend (Next.js)
- **Framework**: Next.js 15 with App Router and React 19
- **Language**: TypeScript for type safety
- **Styling**: Tailwind CSS v4 with Shadcn/ui components
- **State Management**: TanStack Query for server state
- **Authentication**: Clerk client-side auth with RBAC
- **Maps**: React Leaflet for interactive station maps
- **QR Scanning**: ZXing library for charger access
- **Deployment**: Vercel with automatic deployments

### Infrastructure
- **Authentication**: Clerk for user management and JWT
- **Database**: PostgreSQL with SSL (Tortoise ORM + AsyncPG)
- **Cache**: Redis for real-time state
- **Hosting**: Render (backend) + Vercel (frontend)

## 🚀 Development Setup

### Prerequisites
- Node.js 18+ (for frontend)
- Python 3.9+ (for backend)
- PostgreSQL database
- Redis instance
- Clerk account for authentication

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Environment configuration
# Set the following environment variables:
export DATABASE_URL="postgresql://user:password@localhost:5432/ocpp_db"
export REDIS_URL="redis://localhost:6379"
export CLERK_SECRET_KEY="your-clerk-secret-key"
export CLERK_JWT_VERIFICATION_KEY="your-clerk-jwt-key"
export CLERK_WEBHOOK_SECRET="your-clerk-webhook-secret"
export ENVIRONMENT="development"

# Database migrations
aerich upgrade

# Start development server
python main.py
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Environment configuration
# Create .env.local with:
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" >> .env.local
echo "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=your-clerk-publishable-key" >> .env.local
echo "CLERK_SECRET_KEY=your-clerk-secret-key" >> .env.local

# Start development server
npm run dev
```

### Environment Variables

**Backend (.env)**:
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/ocpp_db

# Redis
REDIS_URL=redis://localhost:6379

# Clerk Authentication
CLERK_SECRET_KEY=sk_test_...
CLERK_JWT_VERIFICATION_KEY=...
CLERK_WEBHOOK_SECRET=whsec_...

# Application
ENVIRONMENT=development
PORT=8000
```

**Frontend (.env.local)**:
```bash
# API
NEXT_PUBLIC_API_URL=http://localhost:8000

# Clerk Authentication
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
```

## 📱 Features

### Role-Based Access Control
- **USER Role**: Station finder, QR scanner, personal charging history
- **ADMIN Role**: Full system management, charger control, user administration

### Dashboard Features
- **Real-time Monitoring**: Live charger status and connection monitoring
- **Station Management**: Create and manage charging station locations with maps
- **Charger Control**: Remote start/stop and availability control via OCPP
- **Transaction Tracking**: Complete charging session history with energy analytics
- **User Management**: Admin panel for user administration and wallet management
- **Interactive Maps**: React Leaflet integration for station discovery
- **QR Code Scanning**: Quick charger access via mobile scanning

### OCPP 1.6 Features
- **Full OCPP 1.6 Compliance**: All core messages and remote commands
- **Real-time Communication**: WebSocket-based charge point communication
- **Message Logging**: Complete audit trail of OCPP messages with correlation IDs
- **Connection Management**: Automatic heartbeat monitoring and cleanup
- **Transaction Management**: Complete lifecycle from start to billing
- **Meter Values**: Real-time energy measurement collection

### Financial Integration
- **Wallet System**: User balance management with automatic billing
- **Transaction Billing**: Energy-based charging with automated processing
- **Billing Retry Service**: Automatic recovery for failed transactions
- **Payment Integration**: Ready for payment gateway integration

## 🏗️ API Documentation

### OCPP WebSocket Endpoint
- **Endpoint**: `ws://localhost:8000/ocpp/{charge_point_id}`
- **Authentication**: Database validation of charge point registration
- **Supported Messages**: BootNotification, Heartbeat, StatusNotification, StartTransaction, StopTransaction, MeterValues
- **Remote Commands**: RemoteStartTransaction, RemoteStopTransaction, ChangeAvailability

### REST API Endpoints

**Admin Management** (`/api/admin/` - Requires ADMIN role):
```
# Stations
GET    /api/admin/stations              # List stations with charger count
POST   /api/admin/stations              # Create new station
GET    /api/admin/stations/{id}         # Get station details
PUT    /api/admin/stations/{id}         # Update station
DELETE /api/admin/stations/{id}         # Delete station

# Chargers  
GET    /api/admin/chargers              # List chargers with real-time status
POST   /api/admin/chargers              # Create new charger
GET    /api/admin/chargers/{id}         # Get charger details
PUT    /api/admin/chargers/{id}         # Update charger
DELETE /api/admin/chargers/{id}         # Delete charger
POST   /api/admin/chargers/{id}/remote-start      # Remote start charging
POST   /api/admin/chargers/{id}/remote-stop       # Remote stop charging
POST   /api/admin/chargers/{id}/change-availability # Change charger availability

# Transactions
GET    /api/admin/transactions          # List transactions with analytics
GET    /api/admin/transactions/{id}     # Get transaction details
GET    /api/admin/transactions/{id}/meter-values # Get meter readings
```

**User Management**:
```
GET    /auth/profile                    # Current user profile
GET    /users                           # List users (admin) or current user
GET    /users/{id}                      # User details with wallet info
GET    /users/{id}/transactions         # User transaction history
```

**Legacy APIs** (Backward Compatibility):
```
GET    /api/charge-points               # List connected charge points
POST   /api/charge-points/{id}/request  # Send OCPP command
GET    /api/logs                        # OCPP message logs
```

### API Documentation
- **Interactive Docs**: Available at `http://localhost:8000/docs`
- **OpenAPI Schema**: Available at `http://localhost:8000/openapi.json`

## 🔧 Deployment

### Backend Deployment (Render)
```yaml
# Service Configuration
services:
  - type: web
    name: ocpp-backend
    env: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "python main.py"
    plan: standard
    healthCheckPath: "/"
```

**Environment Variables**: Set DATABASE_URL, REDIS_URL, CLERK_* variables

### Frontend Deployment (Vercel)
- **Framework**: Next.js with automatic optimization
- **Environment Variables**: Set NEXT_PUBLIC_API_URL, NEXT_PUBLIC_CLERK_* variables

## 🧪 Testing

### Backend Testing
```bash
cd backend

# Run all tests
pytest

# Run by category
pytest -m unit          # Fast unit tests (~1 second)
pytest -m integration   # Full OCPP WebSocket tests (~45 seconds)
pytest -m infrastructure # Database/Redis tests (~5 seconds)

# Run with coverage
pytest --cov=. --cov-report=html
```

### OCPP Testing
```bash
# Test complete charging session
python simulators/ocpp_simulator_full_success.py

# Test availability changes
python simulators/ocpp_simulator_change_availability.py

# Test WebSocket connection
websocat ws://localhost:8000/ocpp/CP001
```

## 📊 Project Structure

### Backend Structure
```
backend/
├── main.py                 # FastAPI app with OCPP WebSocket endpoint
├── models.py              # Tortoise ORM models with OCPP enums
├── auth_middleware.py     # Clerk JWT authentication
├── redis_manager.py       # Redis connection management
├── tortoise_config.py     # Database configuration
├── routers/               # API route modules
│   ├── stations.py        # Station management
│   ├── chargers.py        # Charger management with OCPP commands
│   ├── transactions.py    # Transaction tracking
│   ├── users.py           # User management
│   └── webhooks.py        # Clerk webhook handling
├── services/              # Business logic
│   ├── wallet_service.py  # Billing and payments
│   └── billing_retry_service.py # Failed transaction recovery
├── tests/                 # Comprehensive test suite
├── simulators/            # OCPP charger simulators
└── migrations/            # Database migrations
```

### Frontend Structure
```
frontend/
├── app/                   # Next.js App Router
│   ├── layout.tsx         # Root layout with providers
│   ├── page.tsx           # Role-based dashboard
│   ├── auth/              # Authentication pages
│   ├── admin/             # Admin-only management interface
│   ├── stations/          # Station finder with maps
│   ├── scanner/           # QR code scanning
│   └── charge/            # Individual charger interface
├── components/            # React components
│   ├── ui/               # Shadcn/ui components
│   ├── Navbar.tsx        # Role-based navigation
│   ├── RoleWrapper.tsx   # RBAC components
│   └── QRScanner.tsx     # QR code scanning
├── contexts/             # React context providers
├── lib/                  # API integration and utilities
│   ├── api-client.ts     # HTTP client with Clerk auth
│   ├── api-services.ts   # Domain-specific API services
│   └── queries/          # TanStack Query hooks
└── types/                # TypeScript definitions
```

## 🔐 Security Features
- **JWT Authentication**: Clerk-powered token validation with role-based access
- **RBAC**: Comprehensive role separation (ADMIN vs USER)
- **Protected Routes**: Automatic authentication guards
- **CORS Protection**: Configured for secure cross-origin requests
- **Input Validation**: Pydantic schema validation for all API inputs
- **OCPP Security**: Charger registration validation before WebSocket connection
- **Audit Trail**: Complete OCPP message logging for compliance

## 📈 Performance & Scalability
- **Async Architecture**: Full async/await pattern throughout backend
- **Redis Caching**: Real-time connection state with O(1) lookups
- **Database Optimization**: Connection pooling and optimized queries
- **Frontend Optimization**: TanStack Query with intelligent caching
- **Bundle Optimization**: Code splitting and lazy loading
- **CDN Deployment**: Global edge deployment via Vercel

## 🛠️ Known Issues & Technical Debt

### Critical Issue: Boot Notification Transaction Handling
**Location**: `backend/main.py:69-94`
**Issue**: Currently fails ongoing transactions immediately on charger reboot
**Impact**: Users lose active charging sessions unnecessarily
**Solution**: Implement transaction reconciliation with PENDING_RECONCILIATION status

### Performance Improvements
- Database query optimization for N+1 patterns
- Frontend bundle size reduction through code splitting
- Enhanced Redis connection pooling

### Security Enhancements
- OCPP message schema validation
- API rate limiting implementation
- Enhanced audit logging

## 🚀 Future Roadmap

### Short-term (Next 3 months)
- Fix boot notification transaction handling
- Enhanced OCPP command support (Reset, GetConfiguration, UnlockConnector)
- Performance optimizations and query improvements
- Rate limiting and enhanced security

### Medium-term (3-6 months)
- Advanced analytics and reporting dashboard
- Push notifications and offline PWA features
- Multi-tenant architecture support
- Predictive maintenance features

### Long-term (6+ months)
- OCPP 2.0.1 migration path
- Smart grid integration capabilities
- Machine learning for demand forecasting
- Advanced payment systems and roaming support

## 📜 License

This project is licensed under the MIT License.

## 🆘 Support & Documentation

### Additional Resources
- **Architecture Documentation**: `docs/v1/comprehensive-architecture-documentation.md`
- **LLM Context**: `docs/v1/llm-context-document.md`
- **OCPP 1.6 Specification**: Available in `docs/v1/` directory
- **API Documentation**: Available at `/docs` endpoint when running

### Development Commands
```bash
# Backend
cd backend
python main.py                    # Start server
aerich migrate --name "desc"      # Create migration
aerich upgrade                    # Apply migrations
pytest                           # Run tests

# Frontend  
cd frontend
npm run dev                      # Start development
npm run build                    # Build for production
npm run lint                     # Lint code
```

---

**Built with ❤️ for the EV charging ecosystem**

**Current Status**: Production-ready system actively managing real-world charging infrastructure
**Version**: 2.0  
**Last Updated**: January 2025