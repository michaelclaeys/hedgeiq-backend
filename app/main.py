from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import json

from app.cache import UserTier, get_cache, is_cache_empty, get_refresh_rate
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting HedgeIQ API...")
    start_scheduler()
    yield
    logger.info("Shutting down HedgeIQ API...")
    stop_scheduler()

app = FastAPI(
    title="HedgeIQ API",
    description="Bitcoin Options Analytics Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_current_user_tier() -> UserTier:
    return UserTier.STARTER

@app.get("/")
async def root():
    return {"name": "HedgeIQ API", "version": "1.0.0", "status": "online"}

@app.get("/api/health")
async def health_check():
    from app.cache import data_cache
    return {
        "status": "healthy",
        "caches": {
            "pro": {
                "populated": data_cache["pro"]["data"] is not None,
                "last_updated": data_cache["pro"]["last_updated"]
            },
            "starter": {
                "populated": data_cache["starter"]["data"] is not None,
                "last_updated": data_cache["starter"]["last_updated"]
            }
        }
    }

@app.get("/api/dashboard")
async def get_dashboard(tier: UserTier = Depends(get_current_user_tier)):
    if is_cache_empty(tier):
        raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(tier)
    refresh_info = get_refresh_rate(tier)
    
    # Explicitly return only what we need - don't spread cache["data"]
    return {
        "btc_price": cache["data"]["btc_price"],
        "signals": cache["data"]["signals"],
        "metrics": cache["data"]["metrics"],
        "last_updated": cache["last_updated"],
        "refresh_rate": refresh_info["display"],
        "tier": tier.value
    }

@app.get("/api/signals")
async def get_signals(tier: UserTier = Depends(get_current_user_tier)):
    if is_cache_empty(tier):
        raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(tier)
    
    return {
        "signals": cache["data"]["signals"],
        "last_updated": cache["last_updated"],
        "tier": tier.value
    }

@app.get("/api/metrics")
async def get_metrics(tier: UserTier = Depends(get_current_user_tier)):
    if is_cache_empty(tier):
        raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(tier)
    
    return {
        "metrics": cache["data"]["metrics"],
        "btc_price": cache["data"]["btc_price"],
        "last_updated": cache["last_updated"],
        "tier": tier.value
    }