"""
Vanna Exposure Calculator for BTC Options
Vanna = dDelta/dVol (how delta changes with IV)
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt

class VannaCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_vanna(self, S, K, T, r, sigma, option_type):
        """
        Calculate Black-Scholes Vanna
        Vanna = dDelta/dVol
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        vanna = -norm.pdf(d1) * d2 / sigma
        
        return vanna
    
    def calculate_vanna(self, days_out=30):
        """
        Calculate Vanna Exposure for BTC options
        Returns: DataFrame with Vanna by strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING VANNA EXPOSURE")
        print("=" * 60)
        
        # Fetch options data
        df = self.fetcher.get_options_chain(days_out=days_out)
        
        if df.empty:
            print("ERROR: No options data fetched!")
            return pd.DataFrame()
        
        print(f"\nAnalyzing {len(df)} options...")
        
        # Get current BTC price
        btc_price = df['underlying_price'].iloc[0]
        
        # Calculate vanna for each option
        vanna_data = []
        
        for idx, row in df.iterrows():
            S = row['underlying_price']
            K = row['strike']
            T = (row['expiration'] - pd.Timestamp.now()).total_seconds() / (365.25 * 24 * 3600)
            r = 0.0
            sigma = row['mark_iv']
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            if sigma <= 0 or T <= 0:
                continue
            
            if oi == 0:
                oi = 0.01
            
            # Calculate vanna
            vanna = self.black_scholes_vanna(S, K, T, r, sigma, option_type)
            
            # Vanna Exposure = Vanna * Open Interest * S / 100
            if option_type == 'call':
                vanna_exp = vanna * oi * S / 100
            else:
                vanna_exp = vanna * oi * S / 100
            
            vanna_data.append({
                'strike': K,
                'option_type': option_type,
                'expiration': row['expiration'],
                'vanna': vanna,
                'open_interest': oi,
                'volume': volume,
                'vanna_exposure': vanna_exp,
                'mark_iv': sigma * 100,
                'mark_price': row['mark_price']
            })
        
        vanna_df = pd.DataFrame(vanna_data)
        
        # Aggregate Vanna by strike
        vanna_by_strike = vanna_df.groupby('strike').agg({
            'vanna_exposure': 'sum',
            'open_interest': 'sum',
            'volume': 'sum'
        }).reset_index()
        
        vanna_by_strike = vanna_by_strike.sort_values('strike')
        
        # Find key levels
        max_positive_vanna = vanna_by_strike.loc[vanna_by_strike['vanna_exposure'].idxmax()]
        max_negative_vanna = vanna_by_strike.loc[vanna_by_strike['vanna_exposure'].idxmin()]
        
        print("\n" + "-" * 60)
        print("VANNA ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.2f}")
        print(f"Max POSITIVE Vanna: ${max_positive_vanna['strike']:,.0f} | Vanna: {max_positive_vanna['vanna_exposure']:,.0f}")
        print(f"Max NEGATIVE Vanna: ${max_negative_vanna['strike']:,.0f} | Vanna: {max_negative_vanna['vanna_exposure']:,.0f}")
        print("=" * 60)
        
        return vanna_by_strike
    
    def plot_vanna(self, vanna_df):
        """Plot Vanna by strike"""
        if vanna_df.empty:
            print("No data to plot!")
            return
        
        btc_price = self.fetcher.get_btc_price()
        
        plt.figure(figsize=(14, 8))
        
        colors = ['red' if x < 0 else 'green' for x in vanna_df['vanna_exposure']]
        plt.bar(vanna_df['strike'], vanna_df['vanna_exposure'], color=colors, alpha=0.7, width=500)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, label=f'Current BTC: ${btc_price:,.0f}')
        
        plt.xlabel('Strike Price ($)', fontsize=12, fontweight='bold')
        plt.ylabel('Vanna Exposure', fontsize=12, fontweight='bold')
        plt.title('BTC Options Vanna Exposure by Strike', fontsize=14, fontweight='bold')
        plt.legend(fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        plt.savefig('vanna_chart.png', dpi=150, bbox_inches='tight')
        print("\n✓ Chart saved as 'vanna_chart.png'")
        
        plt.show()

if __name__ == "__main__":
    calculator = VannaCalculator()
    vanna_df = calculator.calculate_vanna(days_out=30)
    
    if not vanna_df.empty:
        print("\n" + "-" * 60)
        print("TOP 10 STRIKES BY VANNA MAGNITUDE")
        print("-" * 60)
        top_strikes = vanna_df.copy()
        top_strikes['abs_vanna'] = top_strikes['vanna_exposure'].abs()
        top_strikes = top_strikes.nlargest(10, 'abs_vanna')
        
        for idx, row in top_strikes.iterrows():
            vanna_type = "NEG" if row['vanna_exposure'] < 0 else "POS"
            print(f"${row['strike']:>7,.0f} | Vanna: {row['vanna_exposure']:>12,.0f} | {vanna_type}")
        
        calculator.plot_vanna(vanna_df)