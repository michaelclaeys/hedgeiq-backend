"""
Redis Cache Client
Caches Deribit API responses to avoid rate limits

For now, this is a simple in-memory cache.
Replace with Redis when you deploy to production.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Any
import json

# In-memory cache (replace with Redis in production)
_cache: dict = {}
_cache_ttl: dict = {}

# Default TTL in seconds
DEFAULT_TTL = 30  # 30 seconds - Deribit data doesn't change faster than this


async def init_cache():
    """Initialize cache connection"""
    print("📦 Cache initialized (in-memory mode)")
    print("   ⚠️  For production, configure Redis:")
    print("      REDIS_URL=redis://localhost:6379")


async def close_cache():
    """Close cache connection"""
    _cache.clear()
    _cache_ttl.clear()
    print("📦 Cache closed")


async def get_cached(key: str) -> Optional[Any]:
    """
    Get value from cache
    Returns None if expired or not found
    """
    if key not in _cache:
        return None
    
    # Check TTL
    if key in _cache_ttl:
        if datetime.utcnow() > _cache_ttl[key]:
            # Expired
            del _cache[key]
            del _cache_ttl[key]
            return None
    
    return _cache[key]


async def set_cached(key: str, value: Any, ttl: int = DEFAULT_TTL):
    """
    Set value in cache with TTL
    """
    _cache[key] = value
    _cache_ttl[key] = datetime.utcnow() + timedelta(seconds=ttl)


async def invalidate(key: str):
    """Remove specific key from cache"""
    if key in _cache:
        del _cache[key]
    if key in _cache_ttl:
        del _cache_ttl[key]


async def invalidate_pattern(pattern: str):
    """Remove all keys matching pattern (simple prefix match)"""
    keys_to_remove = [k for k in _cache.keys() if k.startswith(pattern)]
    for key in keys_to_remove:
        await invalidate(key)


# Decorator for caching function results
def cached(ttl: int = DEFAULT_TTL, key_prefix: str = ""):
    """
    Decorator to cache async function results
    
    Usage:
        @cached(ttl=60, key_prefix="gex")
        async def get_gex_data(days_out: int):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Build cache key
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try cache first
            cached_value = await get_cached(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Call function
            result = await func(*args, **kwargs)
            
            # Cache result
            await set_cached(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


"""
=== REDIS PRODUCTION CONFIG ===

When ready for production, replace the in-memory cache with Redis:

import redis.asyncio as redis

_redis: Optional[redis.Redis] = None

async def init_cache():
    global _redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    _redis = redis.from_url(redis_url, decode_responses=True)
    await _redis.ping()
    print(f"📦 Redis connected: {redis_url}")

async def close_cache():
    global _redis
    if _redis:
        await _redis.close()

async def get_cached(key: str) -> Optional[Any]:
    if not _redis:
        return None
    value = await _redis.get(key)
    return json.loads(value) if value else None

async def set_cached(key: str, value: Any, ttl: int = DEFAULT_TTL):
    if _redis:
        await _redis.setex(key, ttl, json.dumps(value, default=str))
"""
