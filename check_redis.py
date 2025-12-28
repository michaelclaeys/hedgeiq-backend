import redis

def verify_cloud_brain():
    # Directly using the URL you provided
    url = "rediss://red-d56d67mr433s73e3c240:WzhMFAUQBbZG4mQulEfnlRH9blAkBGPp@oregon-keyvalue.render.com:6379"
    
    print(f"🔗 Attempting to connect to Render...")

    try:
        # We add ssl_cert_reqs=None because Render uses self-signed certificates 
        # that local laptops often block by default.
        r = redis.from_url(url, decode_responses=True, ssl_cert_reqs=None)
        
        # 1. Test connection
        if r.ping():
            print("✅ Successfully connected to Render Redis!")
        
        # 2. Check current inventory size
        # This looks for keys matching the dealer inventory pattern
        keys = r.keys("dealer_inventory*")
        print(f"📊 Found {len(keys)} inventory records in the cloud.")
        
        # 3. Check memory health
        info = r.info("memory")
        used = info.get("used_memory_human")
        print(f"🧠 Cloud Memory Usage: {used} / 256MB")

    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    verify_cloud_brain()