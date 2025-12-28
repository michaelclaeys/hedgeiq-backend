from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import logging
import os

from dotenv import load_dotenv
load_dotenv()

from redis_state import RedisStateManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check Redis URL at startup
_redis_url = os.getenv("REDIS_URL")
if _redis_url:
    masked = _redis_url.split("@")[-1] if "@" in _redis_url else "local"
    logger.info(f"✓ REDIS_URL: ...@{masked}")
else:
    logger.error("✗ REDIS_URL NOT FOUND - check your .env file")

# Redis singleton
_redis: Optional[RedisStateManager] = None

def get_redis() -> RedisStateManager:
    global _redis
    if _redis is None:
        url = os.getenv("REDIS_URL")
        if not url:
            raise RuntimeError("REDIS_URL not set")
        _redis = RedisStateManager(redis_url=url)
    return _redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("="*50)
    logger.info("HedgeIQ API - FLOW-BASED ONLY")
    logger.info("="*50)
    
    try:
        redis = get_redis()
        gex = redis.get_gex_result()
        if gex:
            logger.info(f"✓ Redis connected, GEX data found")
            logger.info(f"  net_gex: {gex.get('net_gex')}")
            logger.info(f"  flip_level: {gex.get('flip_level')}")
        else:
            logger.warning("⚠ Redis connected but NO GEX data - is stream_processor running?")
    except Exception as e:
        logger.error(f"✗ Redis connection failed: {e}")
    
    yield
    logger.info("Shutting down...")


app = FastAPI(title="HedgeIQ API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"name": "HedgeIQ API", "version": "3.0.0", "mode": "flow_based_only"}


@app.get("/api/health")
async def health():
    try:
        redis = get_redis()
        gex = redis.get_gex_result()
        return {
            "status": "healthy",
            "redis": "connected",
            "gex_available": gex is not None,
            "net_gex": gex.get("net_gex") if gex else None,
            "flip_level": gex.get("flip_level") if gex else None
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.get("/api/gex")
async def get_gex():
    """Flow-based GEX from Redis"""
    try:
        redis = get_redis()
    except Exception as e:
        raise HTTPException(503, f"Redis not available: {e}")
    
    gex = redis.get_gex_result()
    if not gex:
        raise HTTPException(503, "No GEX data. Is stream_processor.py running?")
    
    return {
        "net_gex": gex.get("net_gex"),
        "flip_level": gex.get("flip_level"),
        "btc_price": gex.get("btc_price"),
        "timestamp": gex.get("timestamp"),
        "max_support": gex.get("max_support"),
        "max_resistance": gex.get("max_resistance"),
        "gex_by_strike": gex.get("gex_by_strike", []),
        "data_source": "flow_based"
    }


@app.get("/api/dashboard")
async def dashboard():
    """Main dashboard - flow-based only"""
    try:
        redis = get_redis()
    except Exception as e:
        raise HTTPException(503, f"Redis not available: {e}")
    
    gex = redis.get_gex_result()
    if not gex:
        raise HTTPException(503, "No GEX data. Is stream_processor.py running?")
    
    # Build signals from strike data
    signals = []
    for item in gex.get("gex_by_strike", []):
        strike = item.get("strike", 0)
        gex_val = item.get("gex", 0)
        signals.append({
            "strike": strike,
            "gex": gex_val,
            "type": "support" if gex_val > 0 else "resistance",
            "strength": abs(gex_val)
        })
    
    signals.sort(key=lambda x: abs(x.get("gex", 0)), reverse=True)
    
    max_support = gex.get("max_support")
    max_resistance = gex.get("max_resistance")
    
    return {
        "btc_price": gex.get("btc_price"),
        "signals": signals[:20],
        "metrics": {
            "net_gex": gex.get("net_gex"),
            "flip_level": gex.get("flip_level"),
            "max_support": max_support[0] if max_support else None,
            "max_resistance": max_resistance[0] if max_resistance else None,
        },
        "last_updated": gex.get("timestamp"),
        "data_source": "flow_based"
    }


@app.get("/api/signals")
async def signals():
    """Trading signals - flow-based only"""
    try:
        redis = get_redis()
    except Exception as e:
        raise HTTPException(503, f"Redis not available: {e}")
    
    gex = redis.get_gex_result()
    if not gex:
        raise HTTPException(503, "No GEX data")
    
    signals = []
    for item in gex.get("gex_by_strike", []):
        strike = item.get("strike", 0)
        gex_val = item.get("gex", 0)
        signals.append({
            "strike": strike,
            "gex": gex_val,
            "type": "support" if gex_val > 0 else "resistance",
            "strength": abs(gex_val)
        })
    
    signals.sort(key=lambda x: abs(x.get("gex", 0)), reverse=True)
    
    return {
        "signals": signals[:20],
        "last_updated": gex.get("timestamp"),
        "data_source": "flow_based"
    }


@app.get("/api/metrics")
async def metrics():
    """Summary metrics - flow-based only"""
    try:
        redis = get_redis()
    except Exception as e:
        raise HTTPException(503, f"Redis not available: {e}")
    
    gex = redis.get_gex_result()
    if not gex:
        raise HTTPException(503, "No GEX data")
    
    max_support = gex.get("max_support")
    max_resistance = gex.get("max_resistance")
    
    return {
        "btc_price": gex.get("btc_price"),
        "net_gex": gex.get("net_gex"),
        "flip_level": gex.get("flip_level"),
        "max_support": max_support[0] if max_support else None,
        "max_resistance": max_resistance[0] if max_resistance else None,
        "last_updated": gex.get("timestamp"),
        "data_source": "flow_based"
    }


@app.get("/api/inventory")
async def inventory():
    """Dealer inventory from Redis"""
    try:
        redis = get_redis()
    except Exception as e:
        raise HTTPException(503, f"Redis not available: {e}")
    
    inv = redis.get_full_inventory()
    spot = redis.get_spot_price()
    
    inventory_list = []
    for strike, pos in sorted(inv.items()):
        call_pos = pos.get("call", 0)
        put_pos = pos.get("put", 0)
        if abs(call_pos) > 0.01 or abs(put_pos) > 0.01:
            inventory_list.append({
                "strike": strike,
                "call": call_pos,
                "put": put_pos,
                "net": call_pos + put_pos
            })
    
    return {
        "inventory": inventory_list,
        "count": len(inventory_list),
        "btc_price": spot
    }