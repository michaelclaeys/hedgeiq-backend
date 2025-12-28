import redis
import requests
import numpy as np
from scipy.stats import norm
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
REDIS_URL = os.getenv("REDIS_URL")

# PROCESSED LAEVITAS DATA (Dec 2025)
# Current Spot: ~$87,700
LAEVITAS_OBSERVATIONS = [
    {"strike": 104000, "gex": -154330, "type": "call"},
    {"strike": 102000, "gex": 196610,  "type": "call"},
    {"strike": 100000, "gex": 197100,  "type": "call"},
    {"strike": 98000,  "gex": -65820,  "type": "call"},
    {"strike": 96000,  "gex": 197450,  "type": "call"},
    {"strike": 95000,  "gex": 416130,  "type": "call"},
    {"strike": 94000,  "gex": -183010, "type": "call"},
    {"strike": 93000,  "gex": 97090,   "type": "call"},
    {"strike": 92000,  "gex": 451450,  "type": "call"},
    {"strike": 91000,  "gex": -13930,  "type": "call"},
    {"strike": 90000,  "gex": -468700, "type": "call"},
    {"strike": 89000,  "gex": 1150000, "type": "call"},
    {"strike": 88000,  "gex": 1350000, "type": "call"},
    {"strike": 87000,  "gex": -16250,  "type": "put"},
    {"strike": 86000,  "gex": 197870,  "type": "put"},
    {"strike": 85000,  "gex": 6000,    "type": "put"},
    {"strike": 84000,  "gex": -217000, "type": "put"},
    {"strike": 82000,  "gex": 194000,  "type": "put"},
    {"strike": 80000,  "gex": 236160,  "type": "put"},
    {"strike": 75000,  "gex": 623230,  "type": "put"},
    {"strike": 70000,  "gex": -109920, "type": "put"},
]

def get_deribit_data():
    print("📡 Fetching Deribit market data...")
    summary_url = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
    resp = requests.get(summary_url, params={"currency": "BTC", "kind": "option"})
    options_data = resp.json()["result"]
    
    ticker_url = "https://www.deribit.com/api/v2/public/ticker"
    spot_resp = requests.get(ticker_url, params={"instrument_name": "BTC-PERPETUAL"})
    spot = spot_resp.json()["result"]["last_price"]
    return options_data, spot

def calculate_gamma(spot, strike, dte_years, iv):
    if dte_years <= 0 or iv <= 0: return 0
    d1 = (np.log(spot / strike) + (0.5 * iv**2) * dte_years) / (iv * np.sqrt(dte_years))
    gamma = norm.pdf(d1) / (spot * iv * np.sqrt(dte_years))
    return gamma

def find_best_expiry(options_data, target_strike, target_type):
    now = datetime.utcnow()
    candidates = []
    for opt in options_data:
        name_parts = opt["instrument_name"].split("-")
        try:
            strike = int(name_parts[2])
            opt_type = "call" if name_parts[3] == "C" else "put"
            if strike == target_strike and opt_type == target_type:
                expiry_dt = datetime.strptime(name_parts[1], "%d%b%y")
                dte = (expiry_dt - now).days
                iv = opt.get("mark_iv", 0) / 100
                if dte > 0 and iv > 0:
                    candidates.append({"dte": dte, "iv": iv})
        except: continue
    if not candidates: return None
    candidates.sort(key=lambda x: x["dte"])
    return candidates[0]

def bootstrap():
    if not REDIS_URL:
        print("❌ REDIS_URL not found.")
        return

    r = redis.from_url(REDIS_URL)
    print("🧹 Wiping 'dealer_inventory' to clear the old 'monster' numbers...")
    r.delete("dealer_inventory")
    
    options_data, spot = get_deribit_data()
    print(f"✅ Live Spot: ${spot:,.2f}")
    print("-" * 50)

    for obs in LAEVITAS_OBSERVATIONS:
        strike = obs["strike"]
        target_gex = obs["gex"]
        opt_type = obs["type"]
        
        market_info = find_best_expiry(options_data, strike, opt_type)
        if not market_info:
            continue
            
        dte_years = market_info["dte"] / 365.0
        gamma_val = calculate_gamma(spot, strike, dte_years, market_info["iv"])
        
        if gamma_val == 0: continue

        # The FIXED Unit Formula:
        # GEX Contribution = Inventory * (Gamma * Spot^2 * 0.01)
        dollar_gamma_per_contract = gamma_val * (spot**2) * 0.01
        raw_inventory = target_gex / dollar_gamma_per_contract
        
        # Clean conversion from NumPy
        clean_inventory = float(raw_inventory.item()) if hasattr(raw_inventory, 'item') else float(raw_inventory)
        
        r.hset("dealer_inventory", f"{strike}:{opt_type}", str(clean_inventory))
        print(f"✅ SEEDED {strike} {opt_type.upper()}: {clean_inventory:.2f} contracts")

    print("\n🔥 BOOTSTRAP SUCCESSFUL. Your Redis now matches Laevitas profile.")

if __name__ == "__main__":
    bootstrap()