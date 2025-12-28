import os
import sys
import json
from dotenv import load_dotenv

# Ensure we can import your modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from redis_state import RedisStateManager

def verify():
    load_dotenv()
    
    # Initialize connection
    try:
        state = RedisStateManager()
        print(f"✅ Connected to Redis at {os.getenv('REDIS_URL')}")
    except Exception as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return

    # 1. Check Dealer Inventory (The Input)
    print("\n--- 1. Dealer Inventory Check ---")
    inv = state.get_full_inventory()
    
    if not inv:
        print("⚠️  Inventory is EMPTY. The stream processor might not be processing trades.")
    else:
        print(f"✅ Inventory found for {len(inv)} strikes.")
        # Show a sample
        print("Sample positions:")
        count = 0
        for strike, pos in sorted(inv.items()):
            # only print first 5 active strikes
            if count >= 5: break
            print(f"  ${strike}: Calls={pos.get('call', 0):.2f}, Puts={pos.get('put', 0):.2f}")
            count += 1

    # 2. Check GEX Result (The Output)
    print("\n--- 2. GEX Calculation Check ---")
    gex_data = state.get_gex_result()
    
    if not gex_data:
        print("❌ No GEX result found in Redis (key: 'gex:current').")
        print("Possible causes:")
        print(" - stream_processor.py hasn't run 'recalculate_gex' yet.")
        print(" - Options data (IV/Expiry) failed to fetch from Deribit.")
    else:
        print("✅ GEX Result FOUND!")
        print(f"  Timestamp: {gex_data.get('timestamp', 'N/A')}")
        print(f"  BTC Price used: ${gex_data.get('btc_price', 0):,.2f}")
        print(f"  Net GEX: ${gex_data.get('net_gex', 0):,.0f}")
        
        flip = gex_data.get('flip_level')
        print(f"  Flip Level: ${flip:,.0f}" if flip else "  Flip Level: N/A")
        
        supp = gex_data.get('max_support')
        if supp:
            print(f"  Max Support: ${supp[0]:,.0f} (GEX: {supp[1]:,.0f})")
            
        res = gex_data.get('max_resistance')
        if res:
            print(f"  Max Resistance: ${res[0]:,.0f} (GEX: {res[1]:,.0f})")

if __name__ == "__main__":
    verify()