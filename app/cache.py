from datetime import datetime
from enum import Enum
from typing import Dict, Any

class UserTier(str, Enum):
    """Two subscription tiers"""
    STARTER = "starter"
    PRO = "pro"

# This is our "storage box" - just a Python dictionary in memory
data_cache: Dict[str, Dict[str, Any]] = {
    "pro": {
        "data": None,           # Will hold all Greeks/signals/metrics
        "last_updated": None    # Timestamp when data was fetched
    },
    "starter": {
        "data": None,
        "last_updated": None
    }
}

def get_cache(tier: UserTier) -> Dict[str, Any]:
    """
    Read data from the cache for a specific tier
    Like opening the box and looking inside
    """
    return data_cache[tier.value]

def set_cache(tier: UserTier, data: Dict[str, Any]) -> None:
    """
    Store new data in the cache for a specific tier
    Like putting fresh data into the box
    """
    data_cache[tier.value] = {
        "data": data,
        "last_updated": datetime.utcnow().isoformat()
    }

def is_cache_empty(tier: UserTier) -> bool:
    """
    Check if cache has data yet
    Returns True if box is empty, False if it has data
    """
    return data_cache[tier.value]["data"] is None

def get_refresh_rate(tier: UserTier) -> Dict[str, Any]:
    """
    Return how often each tier's data refreshes
    """
    rates = {
        UserTier.PRO: {"seconds": 60, "display": "1 minute"},
        UserTier.STARTER: {"seconds": 900, "display": "15 minutes"}
    }
    return rates[tier]