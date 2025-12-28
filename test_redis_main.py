import os
from dotenv import load_dotenv
from redis_state import RedisStateManager

load_dotenv()

url = os.getenv("REDIS_URL")
if not url:
    print("❌ ERROR: REDIS_URL not found in .env")
else:
    print(f"🔗 Attempting connection to: {url[:20]}...")
    try:
        state = RedisStateManager(redis_url=url)
        gex = state.get_gex_result()
        if gex:
            print(f"✅ SUCCESS: Found GEX data. Net GEX: {gex.get('net_gex')}")
        else:
            print("⚠️ Connected, but 'gex:current' key is missing in Redis.")
    except Exception as e:
        print(f"❌ Connection failed: {e}")