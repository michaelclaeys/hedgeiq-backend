"""
Deribit Options Data Fetcher
Fetches BTC options data from Deribit API
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time

class DeribitDataFetcher:
    def __init__(self):
        self.base_url = "https://www.deribit.com/api/v2/public"
        
    def get_instruments(self, currency="BTC", kind="option"):
        """Get all available instruments"""
        url = f"{self.base_url}/get_instruments"
        params = {
            "currency": currency,
            "kind": kind,
            "expired": "false"
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        # Handle different response formats
        if 'result' in data:
            return data['result']
        elif isinstance(data, list):
            return data
        else:
            print(f"Unexpected response: {data}")
            return []
    
    def get_book_summary(self, currency="BTC", kind="option"):
        """
        Get book summary for all instruments (includes volume)
        This is a BATCH call - gets all options in one request
        """
        url = f"{self.base_url}/get_book_summary_by_currency"
        params = {
            "currency": currency,
            "kind": kind
        }
        response = requests.get(url, params=params)
        data = response.json()
        return data.get('result', [])
    
    def get_btc_price(self):
        """Get current BTC index price"""
        url = f"{self.base_url}/get_index_price"
        params = {"index_name": "btc_usd"}
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'result' not in data:
            raise Exception("Failed to fetch BTC price from Deribit")
        
        return data['result']['index_price']
    
    def get_options_chain(self, days_out=30):
        """
        Get full options chain for BTC - MULTI-EXPIRY
        Returns: DataFrame with all option data
        """
        print("Fetching BTC options data from Deribit...")
        
        # Get current BTC price
        btc_price = self.get_btc_price()
        print(f"Current BTC Price: ${btc_price:,.2f}")
        
        # FIXED: Use batch call to get all instruments with volume
        book_summary = self.get_book_summary()
        
        if not book_summary:
            print("ERROR: No book summary data!")
            return pd.DataFrame()
        
        # Get all instruments for expiry dates
        instruments = self.get_instruments()
        
        if not instruments:
            print("ERROR: No instruments found!")
            return pd.DataFrame()
        
        # Filter for options expiring within days_out
        target_date = datetime.now() + timedelta(days=days_out)
        
        # Create lookup dict for volume from book summary
        volume_lookup = {}
        for item in book_summary:
            instrument_name = item.get('instrument_name', '')
            volume = item.get('volume', 0)
            open_interest = item.get('open_interest', 0)
            mark_price = item.get('mark_price', 0)
            mark_iv = item.get('mark_iv', 0)
            
            volume_lookup[instrument_name] = {
                'volume': volume,
                'open_interest': open_interest,
                'mark_price': mark_price,
                'mark_iv': mark_iv,
                'underlying_price': item.get('underlying_price', btc_price)
            }
        
        # Build options data for ALL expiries within days_out
        options_data = []
        
        for instrument in instruments:
            exp_timestamp = instrument['expiration_timestamp'] / 1000
            exp_date = datetime.fromtimestamp(exp_timestamp)
            
            # Skip if too far out
            if exp_date > target_date:
                continue
            
            instrument_name = instrument['instrument_name']
            
            # Get data from volume lookup
            if instrument_name not in volume_lookup:
                continue
            
            vol_data = volume_lookup[instrument_name]
            
            option_data = {
                'instrument': instrument_name,
                'strike': instrument['strike'],
                'option_type': instrument['option_type'],
                'expiration': exp_date,
                'expiration_timestamp': exp_timestamp,
                'mark_price': vol_data['mark_price'],
                'mark_iv': vol_data['mark_iv'],
                'open_interest': vol_data['open_interest'],
                'volume': vol_data['volume'],
                'underlying_price': vol_data['underlying_price']
            }
            
            options_data.append(option_data)
        
        df = pd.DataFrame(options_data)
        
        if df.empty:
            print("ERROR: No options data!")
            return df
        
        print(f"\nFetched {len(df)} options")
        
        # Show expiry distribution
        expiry_counts = df.groupby('expiration').size().sort_index()
        print(f"\nExpiry distribution:")
        for exp, count in expiry_counts.items():
            print(f"  {exp.strftime('%Y-%m-%d')}: {count} strikes")
        
        # DEBUG: Volume stats
        total_volume = df['volume'].sum()
        non_zero_volume = (df['volume'] > 0).sum()
        print(f"\n📊 Volume Statistics:")
        print(f"   Total 24h Volume: {total_volume:,.0f} contracts")
        print(f"   Strikes with volume: {non_zero_volume}/{len(df)}")
        
        if total_volume == 0:
            print("⚠️  WARNING: All volumes are 0 - might be off-hours or API issue")
        
        return df

# Test the fetcher
if __name__ == "__main__":
    print("Testing Deribit Data Fetcher...")
    print("-" * 50)
    
    fetcher = DeribitDataFetcher()
    
    # Test 1: Get BTC price
    print("\nTest 1: Fetching BTC price...")
    try:
        btc_price = fetcher.get_btc_price()
        print(f"✓ BTC Price: ${btc_price:,.2f}")
    except Exception as e:
        print(f"✗ Failed: {e}")
    
    # Test 2: Get book summary
    print("\nTest 2: Fetching book summary...")
    summary = fetcher.get_book_summary()
    print(f"✓ Found {len(summary)} instruments in book summary")
    
    if summary:
        sample = summary[0]
        print(f"   Sample: {sample.get('instrument_name')}")
        print(f"   Volume: {sample.get('volume', 0)}")
        print(f"   OI: {sample.get('open_interest', 0)}")
    
    # Test 3: Get multi-expiry chain
    print("\nTest 3: Fetching options chain...")
    df = fetcher.get_options_chain(days_out=30)
    
    if not df.empty:
        print(f"\n✓ Got {len(df)} options")
        print(f"✓ Strikes: {df['strike'].min():.0f} to {df['strike'].max():.0f}")
        print(f"✓ Expiries: {df['expiration'].nunique()}")
    
    print("\n" + "=" * 50)
    print("TESTS COMPLETE")
    print("=" * 50)