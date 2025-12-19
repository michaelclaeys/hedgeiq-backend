"""
Charm Exposure Calculator for BTC Options
Charm = dDelta/dTime (how delta changes as time passes)
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt
from datetime import datetime

class CharmCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_charm(self, S, K, T, r, sigma, option_type):
        """
        Calculate Black-Scholes Charm
        Charm = dDelta/dTime (NOT dGamma/dTime)
        
        S = spot price
        K = strike price
        T = time to expiration (years)
        r = risk-free rate
        sigma = implied volatility
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        # Charm formula (delta decay)
        charm = -(norm.pdf(d1) * (2 * r * T - d2 * sigma * np.sqrt(T))) / (2 * T * sigma * np.sqrt(T))
        
        # Convert to per-day charm (divide by 365)
        charm_per_day = charm / 365
        
        return charm_per_day
    
    def calculate_charm(self, days_out=30):
        """
        Calculate Charm Exposure for BTC options
        Returns: DataFrame with Charm by strike, max charm strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING CHARM EXPOSURE (DELTA DECAY)")
        print("=" * 60)
        
        # Fetch options data
        df = self.fetcher.get_options_chain(days_out=days_out)
        
        if df.empty:
            print("ERROR: No options data fetched!")
            return pd.DataFrame(), 0
        
        print(f"\nAnalyzing {len(df)} options...")
        
        # Get current BTC price
        btc_price = df['underlying_price'].iloc[0]
        
        # Calculate Charm for each option
        charm_data = []
        
        for idx, row in df.iterrows():
            strike = row['strike']
            expiration = row['expiration']
            
            # Calculate time to expiration in years
            expiration_dt = pd.to_datetime(expiration)
            now = datetime.now()
            days_to_exp = (expiration_dt - now).total_seconds() / 86400
            T = days_to_exp / 365.0  # Convert to years
            
            iv = row['mark_iv'] / 100.0  # Convert from percentage to decimal
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            # Skip if no time left or invalid IV
            if T <= 0 or iv <= 0:
                continue
            
            # Calculate Charm using Black-Scholes
            charm = self.black_scholes_charm(
                S=btc_price,
                K=strike,
                T=T,
                r=0.05,  # 5% risk-free rate
                sigma=iv,
                option_type=option_type
            )
            
            # Charm exposure = Charm × Open Interest × BTC per contract
            charm_exposure = charm * oi * 1  # 1 BTC per contract on Deribit
            
            charm_data.append({
                'strike': strike,
                'expiration': expiration,
                'days_to_expiration': days_to_exp,
                'iv': iv,
                'option_type': option_type,
                'open_interest': oi,
                'volume': volume,
                'charm': charm,
                'charm_exposure': charm_exposure,
                'distance_from_spot': abs(strike - btc_price) / btc_price * 100
            })
        
        charm_df = pd.DataFrame(charm_data)
        
        if charm_df.empty:
            print("ERROR: No valid Charm data calculated!")
            return pd.DataFrame(), 0
        
        # Aggregate Charm by strike (calls + puts)
        charm_by_strike = charm_df.groupby('strike').agg({
            'charm_exposure': 'sum',
            'open_interest': 'sum',
            'volume': 'sum',
            'days_to_expiration': 'mean',
            'distance_from_spot': 'first'
        }).reset_index()
        
        charm_by_strike = charm_by_strike.sort_values('strike')
        
        # Find max absolute Charm strike
        max_charm_idx = charm_by_strike['charm_exposure'].abs().idxmax()
        max_charm_strike = charm_by_strike.loc[max_charm_idx, 'strike']
        max_charm_value = charm_by_strike.loc[max_charm_idx, 'charm_exposure']
        
        print(f"\n📊 Charm Analysis Summary:")
        print(f"Current BTC Price: ${btc_price:,.0f}")
        print(f"Max Charm Strike: ${max_charm_strike:,.0f}")
        print(f"Max Charm Value: {max_charm_value:.4f} BTC/day")
        print(f"Distance from Spot: {abs(max_charm_strike - btc_price) / btc_price * 100:.2f}%")
        
        # Show top 5 Charm strikes
        print("\n🔝 Top 5 Charm Strikes:")
        top_charm = charm_by_strike.nlargest(5, 'charm_exposure', keep='all')
        for idx, row in top_charm.iterrows():
            print(f"${row['strike']:>7,.0f} | Charm: {row['charm_exposure']:>10.4f} | OI: {row['open_interest']:>8,.0f} | Vol: {row['volume']:>6,.0f}")
        
        return charm_by_strike, max_charm_strike
    
    def plot_charm_profile(self, charm_df, btc_price):
        """
        Plot Charm exposure profile
        """
        plt.figure(figsize=(14, 8))
        
        plt.bar(charm_df['strike'], charm_df['charm_exposure'], 
                width=charm_df['strike'].diff().median() * 0.8, 
                color=['red' if x < 0 else 'green' for x in charm_df['charm_exposure']],
                alpha=0.7)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, label=f'BTC Spot: ${btc_price:,.0f}')
        plt.axhline(0, color='black', linestyle='-', linewidth=0.5)
        
        plt.xlabel('Strike Price ($)', fontsize=12)
        plt.ylabel('Charm Exposure (BTC/day)', fontsize=12)
        plt.title('Bitcoin Options Charm Exposure Profile\n(Delta Decay Per Day)', fontsize=14, fontweight='bold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()

if __name__ == "__main__":
    calc = CharmCalculator()
    charm_df, max_charm = calc.calculate_charm(days_out=30)
    
    if not charm_df.empty:
        btc_price = charm_df['strike'].median()  # Rough estimate
        calc.plot_charm_profile(charm_df, btc_price)