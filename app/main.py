from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import logging
import httpx

from app.cache import UserTier, get_cache, is_cache_empty, get_refresh_rate
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Supabase config - UPDATE THESE WITH YOUR VALUES
SUPABASE_URL = "https://bjjpfvlcwarloxigoytl.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJqanBmdmxjd2FybG94aWdveXRsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjYwODgyNjcsImV4cCI6MjA4MTY2NDI2N30.cIVZG4D3-SK0qJp_TgcVBO848negG6bXRCSuHk5Motk"

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


async def get_user_tier_from_token(authorization: Optional[str] = Header(None)) -> UserTier:
    """
    Extract user tier from Supabase JWT token.
    Verifies token and looks up tier in profiles table.
    """
    # No token = free tier
    if not authorization:
        logger.info("No auth token - returning free tier")
        return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER
    
    # Extract token from "Bearer <token>"
    try:
        token = authorization.replace("Bearer ", "")
    except:
        return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER
    
    try:
        async with httpx.AsyncClient() as client:
            # Verify token and get user info from Supabase
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"Token verification failed: {response.status_code}")
                return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER
            
            user_data = response.json()
            user_id = user_data.get("id")
            
            if not user_id:
                return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER
            
            # Look up tier from profiles table
            profile_response = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=subscription_tier",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY
                }
            )
            
            if profile_response.status_code == 200:
                profiles = profile_response.json()
                if profiles and len(profiles) > 0:
                    tier_str = profiles[0].get("subscription_tier", "free")
                    logger.info(f"User {user_id} has tier: {tier_str}")
                    
                    # Map string to UserTier enum
                    tier_map = {
                        "free": UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER,
                        "starter": UserTier.STARTER,
                        "pro": UserTier.PRO
                    }
                    return tier_map.get(tier_str, UserTier.STARTER)
            
            return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER
            
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        return UserTier.FREE if hasattr(UserTier, 'FREE') else UserTier.STARTER


def limit_data_for_tier(data: dict, tier: UserTier) -> dict:
    """
    Limit data based on user tier.
    Free users get restricted data.
    """
    tier_value = tier.value if hasattr(tier, 'value') else str(tier)
    
    if tier_value == "free":
        # Free tier: only top 3 signals, limited metrics
        limited_signals = data.get("signals", [])[:3]
        
        # Remove detailed Greeks from signals for free users
        for signal in limited_signals:
            signal["vanna"] = 0
            signal["charm"] = 0
        
        return {
            "btc_price": data.get("btc_price"),
            "signals": limited_signals,
            "metrics": {
                "net_gex": data.get("metrics", {}).get("net_gex", 0),
                "max_pain": data.get("metrics", {}).get("max_pain", 0),
                # Hide detailed metrics for free
                "net_vanna": "Upgrade to view",
                "net_charm": "Upgrade to view",
                "total_oi": "Upgrade to view",
                "total_volume": "Upgrade to view"
            },
            "tier_limited": True,
            "upgrade_message": "Upgrade to Starter or Pro for full data access"
        }
    
    elif tier_value == "starter":
        # Starter tier: all signals, but no vanna/charm details
        signals = data.get("signals", [])
        
        for signal in signals:
            signal["vanna"] = 0
            signal["charm"] = 0
        
        return {
            "btc_price": data.get("btc_price"),
            "signals": signals,
            "metrics": {
                "net_gex": data.get("metrics", {}).get("net_gex", 0),
                "max_pain": data.get("metrics", {}).get("max_pain", 0),
                "net_vanna": "Upgrade to Pro",
                "net_charm": "Upgrade to Pro",
                "total_oi": data.get("metrics", {}).get("total_oi", 0),
                "total_volume": data.get("metrics", {}).get("total_volume", 0)
            },
            "tier_limited": True,
            "upgrade_message": "Upgrade to Pro for Vanna & Charm analysis"
        }
    
    # Pro tier: full data
    return {
        "btc_price": data.get("btc_price"),
        "signals": data.get("signals", []),
        "metrics": data.get("metrics", {}),
        "tier_limited": False
    }


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
async def get_dashboard(tier: UserTier = Depends(get_user_tier_from_token)):
    # Always fetch from pro cache (most complete data)
    # Then limit based on user's tier
    cache_tier = UserTier.PRO
    
    if is_cache_empty(cache_tier):
        # Fallback to starter cache if pro not ready
        cache_tier = UserTier.STARTER
        if is_cache_empty(cache_tier):
            raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(cache_tier)
    refresh_info = get_refresh_rate(tier)
    
    # Apply tier-based data limiting
    limited_data = limit_data_for_tier(cache["data"], tier)
    
    return {
        **limited_data,
        "last_updated": cache["last_updated"],
        "refresh_rate": refresh_info["display"],
        "tier": tier.value if hasattr(tier, 'value') else str(tier)
    }


@app.get("/api/signals")
async def get_signals(tier: UserTier = Depends(get_user_tier_from_token)):
    cache_tier = UserTier.PRO
    
    if is_cache_empty(cache_tier):
        cache_tier = UserTier.STARTER
        if is_cache_empty(cache_tier):
            raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(cache_tier)
    tier_value = tier.value if hasattr(tier, 'value') else str(tier)
    
    signals = cache["data"]["signals"]
    
    # Limit signals for free tier
    if tier_value == "free":
        signals = signals[:3]
    
    return {
        "signals": signals,
        "last_updated": cache["last_updated"],
        "tier": tier_value
    }


@app.get("/api/metrics")
async def get_metrics(tier: UserTier = Depends(get_user_tier_from_token)):
    cache_tier = UserTier.PRO
    
    if is_cache_empty(cache_tier):
        cache_tier = UserTier.STARTER
        if is_cache_empty(cache_tier):
            raise HTTPException(status_code=503, detail="Data is loading")
    
    cache = get_cache(cache_tier)
    limited_data = limit_data_for_tier(cache["data"], tier)
    
    return {
        "metrics": limited_data.get("metrics", {}),
        "btc_price": limited_data.get("btc_price"),
        "last_updated": cache["last_updated"],
        "tier": tier.value if hasattr(tier, 'value') else str(tier)
    }
```

---

**Also, add `httpx` to your `requirements.txt`:**
```
httpx