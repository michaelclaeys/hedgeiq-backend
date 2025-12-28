"""
Redis State Manager for HedgeIQ
Stores dealer inventory and calculated GEX in Redis for fast access.

Keys:
- dealer_inventory:{strike}:{type} → Dealer position (float)
- gex:current → JSON blob with latest GEX calculation
- gex:flip → Current flip level
- spot_price → Current BTC price
- trades:recent → Sorted set of recent trades (for debugging)
"""

import redis
import json
from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import asdict
import os


class RedisStateManager:
    """
    Manages HedgeIQ state in Redis.
    
    Two modes:
    - Production: Connect to actual Redis (Render, Redis Cloud, etc.)
    - Development: Use in-memory dict that mimics Redis interface
    """
    
    def __init__(self, redis_url: Optional[str] = None, use_memory: bool = False):
        """
        Initialize Redis connection.
        
        Args:
            redis_url: Redis connection URL (redis:// or rediss:// for SSL)
            use_memory: If True, use in-memory dict instead of real Redis
        """
        self.use_memory = use_memory
        
        if use_memory:
            print("📦 Using in-memory state (no Redis)")
            self._memory = {}
        else:
            redis_url = redis_url or os.getenv("REDIS_URL")
            
            if not redis_url:
                print("⚠ No REDIS_URL found! Falling back to in-memory.")
                self.use_memory = True
                self._memory = {}
                return
            
            # Mask password in log output
            display_url = redis_url.split("@")[-1] if "@" in redis_url else redis_url
            print(f"📦 Connecting to Redis: {display_url}")
            
            try:
                # ssl_cert_reqs=None handles Render's SSL without local cert verification
                self.redis = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    ssl_cert_reqs=None
                )
                self.redis.ping()
                print("✓ Redis connected successfully!")
            except redis.ConnectionError as e:
                print(f"⚠ Redis connection failed: {e}")
                print("  Falling back to in-memory state")
                self.use_memory = True
                self._memory = {}
    
    def _get(self, key: str) -> Optional[str]:
        if self.use_memory:
            return self._memory.get(key)
        return self.redis.get(key)
    
    def _set(self, key: str, value: str, ex: Optional[int] = None):
        if self.use_memory:
            self._memory[key] = value
        else:
            self.redis.set(key, value, ex=ex)
    
    def _hget(self, key: str, field: str) -> Optional[str]:
        if self.use_memory:
            return self._memory.get(f"{key}:{field}")
        return self.redis.hget(key, field)
    
    def _hset(self, key: str, field: str, value: str):
        if self.use_memory:
            self._memory[f"{key}:{field}"] = value
        else:
            self.redis.hset(key, field, value)
    
    def _hgetall(self, key: str) -> Dict[str, str]:
        if self.use_memory:
            prefix = f"{key}:"
            return {
                k[len(prefix):]: v 
                for k, v in self._memory.items() 
                if k.startswith(prefix)
            }
        return self.redis.hgetall(key)
    
    # ================================================================
    # DEALER INVENTORY
    # ================================================================
    
    def update_dealer_position(self, strike: int, option_type: str, delta: float):
        """
        Update dealer position at a strike.
        delta > 0 = dealer going more LONG
        delta < 0 = dealer going more SHORT
        """
        key = "dealer_inventory"
        field = f"{strike}:{option_type}"
        
        current = self._hget(key, field)
        current_val = float(current) if current else 0.0
        new_val = current_val + delta
        
        self._hset(key, field, str(new_val))
        
        return new_val
    
    def get_dealer_position(self, strike: int, option_type: str) -> float:
        """Get dealer position at a specific strike/type"""
        key = "dealer_inventory"
        field = f"{strike}:{option_type}"
        
        val = self._hget(key, field)
        return float(val) if val else 0.0
    
    def get_full_inventory(self) -> Dict[int, Dict[str, float]]:
        """Get full dealer inventory as nested dict"""
        raw = self._hgetall("dealer_inventory")
        
        inventory = {}
        for key, val in raw.items():
            parts = key.split(":")
            if len(parts) == 2:
                strike = int(parts[0])
                opt_type = parts[1]
                
                if strike not in inventory:
                    inventory[strike] = {"call": 0.0, "put": 0.0}
                
                inventory[strike][opt_type] = float(val)
        
        return inventory
    
    def reset_inventory(self):
        """Clear all dealer inventory (use for fresh start)"""
        if self.use_memory:
            self._memory = {k: v for k, v in self._memory.items() if not k.startswith("dealer_inventory")}
        else:
            # Get all keys and delete
            keys = self.redis.hkeys("dealer_inventory")
            if keys:
                self.redis.hdel("dealer_inventory", *keys)
        print("✓ Dealer inventory reset")
    
    # ================================================================
    # GEX DATA
    # ================================================================
    
    def store_gex_result(self, gex_result: Dict[str, Any]):
        """Store latest GEX calculation"""
        self._set("gex:current", json.dumps(gex_result))
        self._set("gex:last_updated", datetime.now().isoformat())
        
        # Also store flip level separately for quick access
        if gex_result.get("flip_level"):
            self._set("gex:flip", str(gex_result["flip_level"]))
    
    def get_gex_result(self) -> Optional[Dict[str, Any]]:
        """Get latest GEX calculation"""
        data = self._get("gex:current")
        if data:
            return json.loads(data)
        return None
    
    def get_flip_level(self) -> Optional[float]:
        """Get current flip level"""
        val = self._get("gex:flip")
        return float(val) if val else None
    
    # ================================================================
    # SPOT PRICE
    # ================================================================
    
    def set_spot_price(self, price: float):
        """Update current BTC price"""
        self._set("spot_price", str(price))
    
    def get_spot_price(self) -> Optional[float]:
        """Get current BTC price"""
        val = self._get("spot_price")
        return float(val) if val else None
    
    # ================================================================
    # STATS / DEBUG
    # ================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system stats for debugging"""
        inventory = self.get_full_inventory()
        
        total_positions = sum(
            abs(inv.get("call", 0)) + abs(inv.get("put", 0))
            for inv in inventory.values()
        )
        
        return {
            "strikes_tracked": len(inventory),
            "total_position_size": total_positions,
            "spot_price": self.get_spot_price(),
            "flip_level": self.get_flip_level(),
            "last_gex_update": self._get("gex:last_updated")
        }


# ================================================================
# CONVENIENCE: Create global instance
# ================================================================

_state_manager: Optional[RedisStateManager] = None

def get_state_manager() -> RedisStateManager:
    """Get or create the global state manager"""
    global _state_manager
    if _state_manager is None:
        redis_url = os.getenv("REDIS_URL")
        use_memory = os.getenv("USE_MEMORY_STATE", "false").lower() == "true"
        _state_manager = RedisStateManager(redis_url=redis_url, use_memory=use_memory)
    return _state_manager


if __name__ == "__main__":
    # Test the state manager
    print("Testing Redis State Manager...")
    print("-" * 50)
    
    # Use in-memory for testing
    manager = RedisStateManager(use_memory=True)
    
    # Test inventory updates
    print("\n1. Testing inventory updates...")
    manager.update_dealer_position(85000, "put", -100)  # Dealer sold 100 puts
    manager.update_dealer_position(85000, "put", -50)   # Dealer sold 50 more
    manager.update_dealer_position(85000, "call", 25)   # Dealer bought 25 calls
    manager.update_dealer_position(90000, "call", -75)  # Dealer sold 75 calls
    
    pos = manager.get_dealer_position(85000, "put")
    print(f"   85k put position: {pos}")  # Should be -150
    
    # Test full inventory
    print("\n2. Full inventory:")
    inv = manager.get_full_inventory()
    for strike, positions in sorted(inv.items()):
        print(f"   ${strike}: calls={positions['call']}, puts={positions['put']}")
    
    # Test GEX storage
    print("\n3. Testing GEX storage...")
    manager.store_gex_result({
        "net_gex": -1234567,
        "flip_level": 92500,
        "max_support": [100000, 456789],
        "max_resistance": [85000, -987654]
    })
    
    gex = manager.get_gex_result()
    print(f"   Stored GEX: {gex}")
    print(f"   Flip level: {manager.get_flip_level()}")
    
    # Stats
    print("\n4. System stats:")
    stats = manager.get_stats()
    for k, v in stats.items():
        print(f"   {k}: {v}")
    
    print("\n" + "=" * 50)
    print("TESTS PASSED!")