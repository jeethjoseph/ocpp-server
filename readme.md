# OCPP Charging Station Management System

A comprehensive EV charging station management system implementing OCPP 1.6 protocol with modern web technologies. This system provides real-time monitoring, control, and management of electric vehicle charging infrastructure.

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
│  │ • Auth UI       │   │   │ • Station Management            │ │
│  │ • Station Mgmt  │   │   │ • Charger Control               │ │
│  │ • Real-time     │   │   │ • Transaction Tracking          │ │
│  │   Monitoring    │   │   │ • User Management               │ │
│  └─────────────────┘   │   └─────────────────────────────────┘ │
│                        │              │                        │
│  ┌─────────────────┐   │   ┌─────────────────────────────────┐ │
│  │ Supabase Auth   │◄──┼──►│    OCPP WebSocket Server        │ │
│  │                 │   │   │                                 │ │
│  │ • JWT Tokens    │   │   │ • OCPP 1.6 Protocol            │ │
│  │ • User Sessions │   │   │ • Real-time Communication       │ │
│  └─────────────────┘   │   │ • Connection Management         │ │
│                        │   └─────────────────────────────────┘ │
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
- **Database**: PostgreSQL with Tortoise ORM
- **Cache**: Redis for connection state management
- **Authentication**: Supabase JWT validation
- **Protocol**: OCPP 1.6 WebSocket implementation
- **API**: RESTful APIs with OpenAPI documentation
- **Deployment**: Docker on Render

### Frontend (Next.js)
- **Framework**: Next.js 15 with App Router
- **Language**: TypeScript for type safety
- **Styling**: Tailwind CSS with shadcn/ui components
- **State Management**: TanStack Query for server state
- **Authentication**: Supabase client-side auth
- **Deployment**: Vercel with automatic deployments

### Infrastructure
- **Authentication**: Supabase for user management
- **Database**: PostgreSQL (Supabase or managed)
- **Cache**: Redis for real-time state
- **Hosting**: Render (backend) + Vercel (frontend)

## 🚀 Development Setup

### Prerequisites
- Node.js 18+ (for frontend)
- Python 3.9+ (for backend)
- PostgreSQL database
- Redis instance (optional)
- Supabase project

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Environment configuration
cp .env.example .env
# Edit .env with your database and Supabase credentials

# Database setup
python -c "from database import init_db; import asyncio; asyncio.run(init_db())"

# Start development server
python main.py
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Environment configuration
cp .env.example .env.local
# Edit .env.local with your Supabase and API credentials

# Start development server
npm run dev
```

### Environment Variables

**Backend (.env)**:
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/ocpp_db

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_JWT_SECRET=your-jwt-secret

# Redis (optional)
REDIS_URL=redis://localhost:6379

# Environment
ENVIRONMENT=development
```

**Frontend (.env.local)**:
```bash
# API
NEXT_PUBLIC_API_URL=http://localhost:8000

# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

## 📱 Features

### Dashboard Features
- **Real-time Monitoring**: Live charger status and connection monitoring
- **Station Management**: Create and manage charging station locations
- **Charger Control**: Remote start/stop and availability control
- **Transaction Tracking**: Complete charging session history
- **User Management**: Admin panel for user administration
- **Analytics**: Energy consumption and usage statistics

### OCPP Features
- **OCPP 1.6 Compliance**: Full implementation of OCPP 1.6 specification
- **Real-time Communication**: WebSocket-based charge point communication
- **Message Logging**: Complete audit trail of OCPP messages
- **Connection Management**: Automatic heartbeat monitoring and cleanup
- **Transaction Management**: Start/stop transaction handling
- **Meter Values**: Real-time energy measurement collection

### Authentication Features
- **Modern Auth**: Supabase-powered authentication system
- **Multiple Providers**: Email/password and Google OAuth support
- **Role-Based Access**: Admin and user role separation
- **Session Management**: Automatic token refresh and session handling
- **Protected Routes**: Secure access to admin functionality

## 🏗️ API Documentation

### REST API Endpoints

**Station Management**:
- `GET /api/admin/stations` - List all stations
- `POST /api/admin/stations` - Create new station
- `PUT /api/admin/stations/{id}` - Update station
- `DELETE /api/admin/stations/{id}` - Delete station

**Charger Management**:
- `GET /api/admin/chargers` - List all chargers
- `POST /api/admin/chargers` - Create new charger
- `PUT /api/admin/chargers/{id}` - Update charger
- `DELETE /api/admin/chargers/{id}` - Delete charger
- `POST /api/admin/chargers/{id}/remote-start` - Remote start charging
- `POST /api/admin/chargers/{id}/remote-stop` - Remote stop charging

**Transaction Management**:
- `GET /api/admin/transactions` - List all transactions
- `GET /api/admin/transactions/{id}/meter-values` - Get meter readings
- `POST /api/admin/transactions/{id}/force-stop` - Force stop transaction

**OCPP WebSocket**:
- `WS /ocpp/{charge_point_id}` - OCPP charge point connection

### API Documentation
- **Interactive Docs**: Available at `http://localhost:8000/docs`
- **OpenAPI Schema**: Available at `http://localhost:8000/openapi.json`

## 🔧 Deployment

### Backend Deployment (Render)
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Environment Variables: Set DATABASE_URL, SUPABASE_* variables

### Frontend Deployment (Vercel)
- Framework: Next.js
- Environment Variables: Set NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_* variables

## 🧪 Testing

### Backend Testing
```bash
cd backend
pytest
```

### OCPP Testing
```bash
# Test WebSocket connection
websocat ws://localhost:8000/ocpp/CP001

# Test API endpoints
curl http://localhost:8000/api/admin/chargers
```

## 📊 File Structure

### Backend Structure
```
backend/
├── main.py                 # FastAPI app entrypoint
├── models.py              # Tortoise ORM models
├── database.py            # Database configuration
├── schemas.py             # Pydantic models
├── crud.py                # CRUD operations
├── auth_middleware.py     # JWT validation
├── redis_manager.py       # Redis connection management
├── routers/               # API route modules
│   ├── stations.py
│   ├── chargers.py
│   └── transactions.py
├── migrations/            # Database migrations
├── tests/                 # Test suite
└── requirements.txt
```

### Frontend Structure
```
frontend/
├── app/                   # Next.js App Router
│   ├── auth/             # Authentication pages
│   ├── stations/         # Station management
│   └── chargers/         # Charger monitoring
├── components/           # React components
│   ├── ui/              # shadcn/ui components
│   └── auth/            # Auth-specific components
├── contexts/            # React context providers
├── lib/                 # Utilities and API client
└── types/              # TypeScript definitions
```

## 🔐 Security Features
- **JWT Authentication**: Supabase-powered token validation
- **Role-Based Access**: Admin vs User permissions
- **Protected Routes**: Automatic auth guards
- **CORS Protection**: Secure cross-origin requests
- **Input Validation**: Pydantic schema validation

## 📜 License

This project is licensed under the MIT License.

## 🆘 Support

### Useful Resources
- [OCPP 1.6 Specification](https://www.openchargealliance.org/protocols/ocpp-16/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js Documentation](https://nextjs.org/docs)
- [Supabase Documentation](https://supabase.com/docs)

---

**Built with ❤️ for the EV charging ecosystem**
