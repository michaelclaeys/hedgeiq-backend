"""
Gamma Exposure (GEX) Calculator for BTC Options
Calculates dealer gamma exposure at each strike
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt

class GEXCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_gamma(self, S, K, T, r, sigma, option_type):
        """
        Calculate Black-Scholes Gamma
        S = spot price
        K = strike price
        T = time to expiration (years)
        r = risk-free rate
        sigma = implied volatility
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        return gamma
    
    def calculate_gex(self, days_out=30):
        """
        Calculate Gamma Exposure for BTC options
        Returns: DataFrame with GEX by strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING GAMMA EXPOSURE (GEX)")
        print("=" * 60)
        
        # Fetch options data
        df = self.fetcher.get_options_chain(days_out=days_out)
        
        if df.empty:
            print("ERROR: No options data fetched!")
            return pd.DataFrame()
        
        print(f"\nAnalyzing {len(df)} options...")
        
        # Get current BTC price
        btc_price = df['underlying_price'].iloc[0]
        
        # Calculate gamma for each option
        gex_data = []
        
        for idx, row in df.iterrows():
            S = row['underlying_price']
            K = row['strike']
            T = (row['expiration'] - pd.Timestamp.now()).total_seconds() / (365.25 * 24 * 3600)
            r = 0.0
            sigma = row['mark_iv']
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            if sigma <= 0 or T <= 0 or oi == 0:
                continue
            
            # Calculate gamma
            gamma = self.black_scholes_gamma(S, K, T, r, sigma, option_type)
            
            # GEX = Gamma * Open Interest * S^2 / 100
            # Sign convention (SpotGamma standard):
            # Calls = negative GEX (dealers short gamma)
            # Puts = positive GEX (dealers long gamma from selling puts)
            
            if option_type == 'call':
                gex = -gamma * oi * (S ** 2) / 100
            else:
                gex = gamma * oi * (S ** 2) / 100
            
            gex_data.append({
                'strike': K,
                'option_type': option_type,
                'expiration': row['expiration'],
                'gamma': gamma,
                'open_interest': oi,
                'volume': volume,
                'gex': gex,
                'mark_iv': sigma * 100,
                'mark_price': row['mark_price']
            })
        
        gex_df = pd.DataFrame(gex_data)
        
        # Aggregate GEX by strike
        gex_by_strike = gex_df.groupby('strike').agg({
            'gex': 'sum',
            'open_interest': 'sum',
            'volume': 'sum'
        }).reset_index()
        
        gex_by_strike = gex_by_strike.sort_values('strike')
        
        # Filter to relevant strikes (±15% of spot)
        relevant_gex = gex_by_strike[
            (gex_by_strike['strike'] >= btc_price * 0.85) & 
            (gex_by_strike['strike'] <= btc_price * 1.15)
        ].copy()
        
        # Find key levels
        max_negative_gex = gex_by_strike.loc[gex_by_strike['gex'].idxmin()]
        max_positive_gex = gex_by_strike.loc[gex_by_strike['gex'].idxmax()]
        
        # Zero GEX level
        if not relevant_gex.empty:
            relevant_gex['gex_cumsum'] = relevant_gex['gex'].cumsum()
            zero_cross_idx = relevant_gex['gex_cumsum'].abs().idxmin()
            zero_cross = relevant_gex.loc[[zero_cross_idx]]
        else:
            zero_cross = pd.DataFrame()
        
        # Add cumsum to full dataframe
        gex_by_strike['gex_cumsum'] = gex_by_strike['gex'].cumsum()
        
        print("\n" + "-" * 60)
        print("GEX ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.2f}")
        print(f"Max NEGATIVE GEX: ${max_negative_gex['strike']:,.0f} | GEX: {max_negative_gex['gex']:,.0f}")
        print(f"Max POSITIVE GEX: ${max_positive_gex['strike']:,.0f} | GEX: {max_positive_gex['gex']:,.0f}")
        
        if not zero_cross.empty:
            print(f"Zero GEX Level: ${zero_cross.iloc[0]['strike']:,.0f}")
        
        print("=" * 60)
        
        return gex_by_strike
    
    def plot_gex(self, gex_df):
        """Plot GEX by strike"""
        if gex_df.empty:
            print("No data to plot!")
            return
        
        btc_price = self.fetcher.get_btc_price()
        
        plt.figure(figsize=(14, 8))
        
        colors = ['red' if x < 0 else 'green' for x in gex_df['gex']]
        plt.bar(gex_df['strike'], gex_df['gex'], color=colors, alpha=0.7, width=500)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, label=f'Current BTC: ${btc_price:,.0f}')
        
        plt.xlabel('Strike Price ($)', fontsize=12, fontweight='bold')
        plt.ylabel('Gamma Exposure (GEX)', fontsize=12, fontweight='bold')
        plt.title('BTC Options Gamma Exposure (GEX) by Strike', fontsize=14, fontweight='bold')
        plt.legend(fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        plt.savefig('gex_chart.png', dpi=150, bbox_inches='tight')
        print("\n✓ Chart saved as 'gex_chart.png'")
        
        plt.show()

if __name__ == "__main__":
    calculator = GEXCalculator()
    gex_df = calculator.calculate_gex(days_out=30)
    
    if not gex_df.empty:
        print("\n" + "-" * 60)
        print("TOP 10 STRIKES BY GEX MAGNITUDE")
        print("-" * 60)
        top_strikes = gex_df.copy()
        top_strikes['abs_gex'] = top_strikes['gex'].abs()
        top_strikes = top_strikes.nlargest(10, 'abs_gex')
        
        for idx, row in top_strikes.iterrows():
            gex_type = "NEG" if row['gex'] < 0 else "POS"
            print(f"${row['strike']:>7,.0f} | GEX: {row['gex']:>12,.0f} | Vol: {row['volume']:>6,.0f} | {gex_type}")
        
        calculator.plot_gex(gex_df)