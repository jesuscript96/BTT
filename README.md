# BTT - Backtesting Trading Tool

A full-stack trading analysis and backtesting platform for analyzing short-selling strategies with real-time market data from Massive API.

## 🏗️ Architecture

- **Frontend**: Next.js 15 + TypeScript + Tailwind CSS
- **Backend**: FastAPI + Python 3.14
- **Database**: DuckDB (embedded analytics database)
- **Data Source**: Massive API (market data)

## 📦 Project Structure

```
BTT/
├── frontend/          # Next.js application
├── backend/           # FastAPI server
├── .agent/            # AI agent configuration
└── data/              # Local data storage (gitignored)
```

## 🚀 Local Development

### Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:
```
MASSIVE_API_KEY=your_api_key_here
MASSIVE_API_BASE_URL=https://api.polygon.io
```

Run the backend (always through the safe launcher — never `uvicorn --reload`,
which leaves orphan workers holding `local_data.duckdb`; see
`docs/REGLA_ARRANQUE_BACKEND_LOCAL.md`):
```bash
# Windows
scripts\arrancar_backend.bat
# macOS / Linux (venv activated)
python scripts/run_backend_safe.py
```

### Frontend Setup

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

Run the frontend:
```bash
npm run dev
```

Visit `http://localhost:3000`

## 🌐 Deployment

### Vercel (Frontend)

1. Push to GitHub
2. Import repository in Vercel
3. Set root directory to `frontend`
4. Add environment variable: `NEXT_PUBLIC_API_URL` (your backend URL)
5. Deploy

### Backend Deployment Options

- **Railway**: Supports Python + DuckDB
- **Render**: Free tier available
- **Fly.io**: Good for persistent storage

## 📊 Features

- Real-time market data ingestion
- Advanced filtering and analysis
- Custom trading metrics calculation
- Time-series aggregation
- CSV export functionality
- Interactive dashboard with charts

## 🔑 Environment Variables

### Backend
- `MASSIVE_API_KEY`: Your Polygon.io API key
- `MASSIVE_API_BASE_URL`: API base URL (default: https://api.polygon.io)

### Frontend
- `NEXT_PUBLIC_API_URL`: Backend API URL

## 📝 License

Private - All Rights Reserved
