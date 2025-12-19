# HedgeIQ Backend API

FastAPI server for BTC options Greeks analytics.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment config
cp .env.example .env

# 4. Run development server
python main.py
# or
uvicorn main:app --reload --port 8000
```

Server runs at `http://localhost:8000`

## API Endpoints

### Greeks

| Endpoint | Description |
|----------|-------------|
| `GET /api/gex?days_out=30` | Gamma Exposure by strike |
| `GET /api/vanna?days_out=30` | Vanna Exposure by strike |
| `GET /api/charm?days_out=30` | Charm (delta decay) by strike |
| `GET /api/maxpain?days_out=30` | Max Pain strike |
| `GET /api/price` | Current BTC price |

### Dashboard

| Endpoint | Description |
|----------|-------------|
| `GET /api/levels?days_out=30&top_n=10` | Key levels with full analysis |
| `GET /api/metrics?days_out=30` | Summary metrics for dashboard cards |

### System

| Endpoint | Description |
|----------|-------------|
| `GET /` | API info |
| `GET /health` | Health check |
| `GET /docs` | Swagger UI (auto-generated) |
| `GET /redoc` | ReDoc (auto-generated) |

## Response Format

All endpoints return:

```json
{
  "success": true,
  "timestamp": "2024-01-15T12:00:00Z",
  "btc_price": 97500.00,
  "data": { ... }
}
```

Errors return:

```json
{
  "detail": "Error message"
}
```

## Project Structure

```
hedgeiq-backend/
├── main.py              # FastAPI app entry point
├── routers/
│   ├── greeks.py        # Individual Greek endpoints
│   └── levels.py        # Combined analysis endpoints
├── services/
│   ├── deribit_data.py  # Deribit API client
│   ├── calculate_gex.py
│   ├── calculate_vanna.py
│   ├── calculate_charm.py
│   ├── calculate_max_pain.py
│   └── trading_signals.py
├── cache/
│   └── redis_client.py  # Caching layer
├── requirements.txt
└── .env.example
```

## Frontend Integration

Your frontend should call these endpoints:

```javascript
// Dashboard metrics (for the cards)
const metrics = await fetch('http://localhost:8000/api/metrics');

// Key levels (for the table/chart)
const levels = await fetch('http://localhost:8000/api/levels?top_n=10');

// Individual Greeks (for detailed views)
const gex = await fetch('http://localhost:8000/api/gex');
```

## Next Steps

1. **Add caching**: Uncomment Redis in requirements.txt, configure REDIS_URL
2. **Add WebSocket**: For real-time updates (see websocket branch)
3. **Add auth**: User accounts (see auth branch)
4. **Deploy**: Railway, Render, or your own VPS

## Rate Limits

Deribit public API has rate limits. The cache layer (30s TTL) protects against this.
If you hit limits, increase CACHE_TTL_SECONDS in .env.
