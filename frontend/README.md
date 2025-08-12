# OCPP Admin Dashboard

A Next.js admin dashboard for managing EV charging stations and chargers with OCPP 1.6 support.

## Features

- **Station Management**: Full CRUD operations for charging stations
- **Charger Management**: Filterable table view with search and status filtering
- **Availability Control**: Toggle charger availability with real-time OCPP commands
- **Dashboard**: Overview of system statistics and quick actions
- **Responsive Design**: Works on desktop and mobile devices

## Prerequisites

- Node.js 18+ 
- Running OCPP backend server (Python FastAPI)

## Getting Started

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Configure environment:**
   Create `.env.local` file with:
   ```
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

3. **Start development server:**
   ```bash
   npm run dev
   ```

4. **Open browser:**
   Navigate to [http://localhost:3000](http://localhost:3000)

## API Integration

The dashboard integrates with the following backend endpoints:

### Stations API
- `GET /api/admin/stations` - List stations with pagination and search
- `POST /api/admin/stations` - Create new station
- `GET /api/admin/stations/{id}` - Get station details with chargers
- `PUT /api/admin/stations/{id}` - Update station
- `DELETE /api/admin/stations/{id}` - Delete station

### Chargers API
- `GET /api/admin/chargers` - List chargers with filtering
- `POST /api/admin/chargers` - Create/onboard new charger
- `GET /api/admin/chargers/{id}` - Get charger details
- `PUT /api/admin/chargers/{id}` - Update charger
- `DELETE /api/admin/chargers/{id}` - Delete charger
- `POST /api/admin/chargers/{id}/change-availability` - Change availability
- `POST /api/admin/chargers/{id}/remote-stop` - Stop charging session

## Project Structure

```
frontend/
├── app/
│   ├── page.tsx              # Dashboard homepage
│   ├── stations/
│   │   └── page.tsx          # Stations management
│   ├── chargers/
│   │   └── page.tsx          # Chargers management
│   ├── layout.tsx            # Root layout with navigation
│   └── globals.css           # Global styles
├── components/
│   └── Navbar.tsx            # Navigation component
├── lib/
│   ├── api.ts               # API client configuration
│   └── api-services.ts      # API service functions
├── types/
│   └── api.ts               # TypeScript type definitions
└── .env.local               # Environment configuration
```

## Usage

### Managing Stations
1. Navigate to **Stations** page
2. Click **Add Station** to create new stations
3. Use search bar to find specific stations
4. Click **Edit** or **Delete** for existing stations

### Managing Chargers
1. Navigate to **Chargers** page
2. Use filters to find chargers by status, station, or search term
3. Click **Add Charger** to onboard new chargers
4. Toggle the availability switch to change charger status
5. The system sends OCPP ChangeAvailability commands to connected chargers

### Dashboard Overview
- View system statistics (total stations, chargers, availability)
- Quick action buttons for common tasks
- Real-time status updates

## Development

Built with:
- **Next.js 15** - React framework
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **React Hooks** - State management

## Production Deployment

1. **Build the application:**
   ```bash
   npm run build
   ```

2. **Start production server:**
   ```bash
   npm start
   ```

3. **Configure environment variables** for production API endpoint

## Troubleshooting

- **API Connection Issues**: Verify backend server is running on correct port
- **CORS Errors**: Ensure backend allows frontend domain
- **Build Errors**: Check TypeScript types and imports
