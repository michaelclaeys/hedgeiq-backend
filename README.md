# HedgeIQ 2.0 - Phase 1: Flow-Based GEX

## What This Is

This is the complete Phase 1 of your HedgeIQ rebuild. It replaces your broken assumption-based GEX calculation with real-time flow-based tracking.

**The key insight:** Your old code assumed dealers are ALWAYS short calls and long puts. But at $85k, if retail is aggressively buying puts (bearish bet), dealers are SHORT those puts - which your code got backwards.

**The fix:** Track every trade's `taker_side` from Deribit WebSocket. Build actual dealer inventory. Calculate GEX from real positions.

## Files Included

```
├── deribit_websocket.py     # WebSocket trade listener
├── flow_based_gex.py        # New GEX calculator using dealer inventory  
├── redis_state.py           # Redis state manager for persistence
├── stream_processor.py      # Integrated system (run this!)
├── requirements_phase1.txt  # Dependencies
└── README.md                # This file
```

## Quick Start

### 1. Install Dependencies

```bash
cd hedgeiq-backend
pip install -r requirements_phase1.txt
```

### 2. Run Without Redis (Dev Mode)

For testing locally without Redis:

```bash
export USE_MEMORY_STATE=true
python stream_processor.py
```

### 3. Run With Redis (Production)

For production with persistence:

```bash
# Start local Redis (if not using cloud)
docker run -d -p 6379:6379 redis

# Or use Render Redis / Redis Cloud
export REDIS_URL=redis://localhost:6379
python stream_processor.py
```

## What You'll See

```
╔═══════════════════════════════════════════════════════════╗
║                  HEDGEIQ STREAM PROCESSOR                 ║
╚═══════════════════════════════════════════════════════════╝

✓ Fetched 847 options, spot: $94,250.00
✓ Connected to Deribit WebSocket
✓ Subscribed to BTC options trades

🎯 Listening for trades...

🟢 BUY 5.0 PUT@85000 → Dealer: -5.0
🟢 BUY 2.5 CALL@95000 → Dealer: -2.5
🔴 SELL 1.0 PUT@90000 → Dealer: +1.0
📊 GEX Update: NEGATIVE γ | Net: $-1,234,567 | Flip: $91,500
```

## How It Works

1. **WebSocket connects** to Deribit's `trades.option.BTC.raw` channel
2. **Every trade** has a `direction` field ("buy" or "sell") - this is the taker side
3. **If taker bought:** Dealer sold that option → Dealer position goes SHORT
4. **If taker sold:** Dealer bought that option → Dealer position goes LONG
5. **GEX is calculated** using actual dealer positions, not assumptions
6. **Results stored in Redis** for your FastAPI to serve

## Integration With Your Existing Backend

Once this is running, you need to modify your `main.py` to read from Redis instead of calling the old `calculate_gex.py`.

Replace:
```python
# OLD
from services.calculate_gex import GEXCalculator
gex = GEXCalculator().calculate_gex()
```

With:
```python
# NEW
from redis_state import get_state_manager
state = get_state_manager()
gex_result = state.get_gex_result()
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────┐
│                  RENDER                          │
├─────────────────────────────────────────────────┤
│  ┌──────────────────┐    ┌──────────────────┐  │
│  │ stream_processor │───▶│     REDIS        │  │
│  │ (Worker)         │    │                  │  │
│  └──────────────────┘    └────────┬─────────┘  │
│                                   │            │
│  ┌──────────────────┐             │            │
│  │ FastAPI          │◀────────────┘            │
│  │ (Web Service)    │                          │
│  └──────────────────┘                          │
└─────────────────────────────────────────────────┘
```

On Render, you'll have:
- **Web Service:** Your FastAPI app (main.py)
- **Background Worker:** stream_processor.py
- **Redis:** Render Redis addon

## Testing The Components

### Test WebSocket Only
```bash
python deribit_websocket.py
```
This just prints trades - no Redis needed.

### Test GEX Calculator
```bash
python flow_based_gex.py
```
This runs with mock data to show the calculation logic.

### Test Redis State
```bash
python redis_state.py
```
This tests state management with in-memory mode.

## Next Steps (Phase 2-6)

After Phase 1 is working:

- **Phase 2:** Build proper GEX engine with time weighting, vol surface
- **Phase 3:** Update FastAPI endpoints to serve from Redis
- **Phase 4:** Point your frontend at new endpoints (minimal changes)
- **Phase 5:** Upgrade Vanna/Charm with same flow-based logic
- **Phase 6:** Deploy to Render with proper monitoring

## Key Differences From Old System

| Aspect | Old (Broken) | New (Fixed) |
|--------|--------------|-------------|
| Data Source | REST polling every 1-5min | WebSocket real-time |
| Dealer Position | Assumed (short calls, long puts) | Actual from trade flow |
| State | In-memory cache | Redis (persistent) |
| Update Speed | 1-5 minutes | Every trade (100ms) |
| $85k Put Wall | Showed as Call Wall ❌ | Shows as Put Wall ✅ |

## Troubleshooting

### "WebSocket connection refused"
Check your network. Some corporate firewalls block WebSocket. Try a different network.

### "Redis connection failed"
Either start local Redis or set `USE_MEMORY_STATE=true`.

### No trades showing
Deribit options volume is lower than spot. Wait a few minutes, especially during low-volume hours (overnight UTC).

### GEX values look wrong
Give it 15-30 minutes to build up inventory from trades. Initial values will be incomplete.
