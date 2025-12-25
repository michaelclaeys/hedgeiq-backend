"""
Vanna Exposure Calculator for BTC Options - FIXED FOR CRYPTO
Vanna = dDelta/dVol (how delta changes with IV)

CHANGES FROM ORIGINAL:
1. Removed /100 equity multiplier (crypto contract size = 1 BTC)
2. Added dealer positioning sign convention for calls vs puts
3. IV already comes as decimal from Deribit, don't divide again
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from services.deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt


class VannaCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_vanna(self, S, K, T, r, sigma):
        """
        Calculate Black-Scholes Vanna
        
        Vanna = dDelta/dVol = dVega/dSpot
        
        Interpretation:
        - Positive Vanna: Delta increases when IV increases
        - Negative Vanna: Delta decreases when IV increases
        
        For dealer hedging:
        - If dealer is SHORT an option with positive vanna:
          Rising IV → Delta increases → Dealer must SELL more underlying
        - If dealer is LONG an option with positive vanna:
          Rising IV → Delta increases → Dealer must BUY more underlying
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        # Vanna formula: -N'(d1) * d2 / sigma
        vanna = -norm.pdf(d1) * d2 / sigma
        
        return vanna
    
    def calculate_vanna(self, days_out=30):
        """
        Calculate Vanna Exposure for BTC options
        
        Formula for crypto (contract size = 1 BTC):
        Vanna Exposure = Vanna × OI × Spot × ContractSize
        
        Sign Convention (dealer positioning):
        - Calls: Dealers SHORT → flip sign (negative exposure)
        - Puts: Dealers LONG → keep sign (positive exposure)
        
        Interpretation:
        - Positive Vanna Exposure at a strike:
          If IV rises, dealers will SELL at this level (resistance in vol expansion)
        - Negative Vanna Exposure at a strike:
          If IV rises, dealers will BUY at this level (support in vol expansion)
        
        Returns: DataFrame with Vanna by strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING VANNA EXPOSURE - CRYPTO ADJUSTED")
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
            # CRITICAL: Deribit returns mark_iv as PERCENTAGE (e.g., 65 = 65%)
            # Must divide by 100 to get decimal for Black-Scholes
            sigma = row['mark_iv'] / 100.0
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            # Skip invalid data
            if sigma <= 0 or T <= 0:
                continue
            
            # Skip zero OI but keep small positions
            if oi == 0:
                continue
            
            # Skip options expiring in < 2 hours
            if T < (2 / (365.25 * 24)):
                continue
            
            # Calculate raw vanna
            vanna = self.black_scholes_vanna(S, K, T, r, sigma)
            
            # =============================================================
            # CRYPTO VANNA EXPOSURE (Contract Size = 1 BTC)
            # =============================================================
            contract_size = 1
            
            # Dollar vanna exposure
            dollar_vanna = vanna * S * contract_size * oi
            
            # Apply dealer positioning
            if option_type == 'call':
                # Dealers are SHORT calls
                # If vanna > 0 and IV rises, delta increases
                # Short call means dealer delta becomes more negative
                # So dealer must SELL more underlying (flip sign)
                vanna_exp = -dollar_vanna
            else:
                # Dealers are LONG puts (sold to retail)
                # If vanna > 0 and IV rises, (absolute) delta increases
                # Long put means dealer needs to BUY more underlying
                vanna_exp = dollar_vanna
            
            vanna_data.append({
                'strike': K,
                'option_type': option_type,
                'expiration': row['expiration'],
                'vanna': vanna,
                'open_interest': oi,
                'volume': volume,
                'vanna_exposure': vanna_exp,
                'mark_iv': row['mark_iv'],  # Keep as percentage for display
                'mark_price': row['mark_price']
            })
        
        vanna_df = pd.DataFrame(vanna_data)
        
        if vanna_df.empty:
            print("ERROR: No valid Vanna data calculated!")
            return pd.DataFrame()
        
        # Aggregate Vanna by strike
        vanna_by_strike = vanna_df.groupby('strike').agg({
            'vanna_exposure': 'sum',
            'open_interest': 'sum',
            'volume': 'sum'
        }).reset_index()
        
        vanna_by_strike = vanna_by_strike.sort_values('strike')
        
        # Find key levels
        max_positive_idx = vanna_by_strike['vanna_exposure'].idxmax()
        max_negative_idx = vanna_by_strike['vanna_exposure'].idxmin()
        
        max_positive_vanna = vanna_by_strike.loc[max_positive_idx]
        max_negative_vanna = vanna_by_strike.loc[max_negative_idx]
        
        # Net vanna
        net_vanna = vanna_by_strike['vanna_exposure'].sum()
        
        print("\n" + "-" * 60)
        print("VANNA ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.2f}")
        
        print(f"\nNet Vanna: ${net_vanna:,.0f}")
        if net_vanna > 0:
            print("  → If IV RISES: Dealers will NET SELL (bearish pressure)")
            print("  → If IV FALLS: Dealers will NET BUY (bullish pressure)")
        else:
            print("  → If IV RISES: Dealers will NET BUY (bullish pressure)")
            print("  → If IV FALLS: Dealers will NET SELL (bearish pressure)")
        
        print(f"\nMax POSITIVE Vanna: ${max_positive_vanna['strike']:,.0f}")
        print(f"   Exposure: ${max_positive_vanna['vanna_exposure']:,.0f}")
        print(f"   → IV rise = dealers SELL here (resistance in vol expansion)")
        
        print(f"\nMax NEGATIVE Vanna: ${max_negative_vanna['strike']:,.0f}")
        print(f"   Exposure: ${max_negative_vanna['vanna_exposure']:,.0f}")
        print(f"   → IV rise = dealers BUY here (support in vol expansion)")
        
        print("=" * 60)
        
        return vanna_by_strike
    
    def plot_vanna(self, vanna_df, save_path='vanna_chart.png'):
        """Plot Vanna by strike"""
        if vanna_df.empty:
            print("No data to plot!")
            return
        
        btc_price = self.fetcher.get_btc_price()
        
        # Filter to relevant range
        plot_df = vanna_df[
            (vanna_df['strike'] >= btc_price * 0.85) & 
            (vanna_df['strike'] <= btc_price * 1.15)
        ].copy()
        
        plt.figure(figsize=(14, 8))
        
        colors = ['red' if x > 0 else 'green' for x in plot_df['vanna_exposure']]
        
        if len(plot_df) > 1:
            bar_width = plot_df['strike'].diff().median() * 0.8
        else:
            bar_width = 1000
        
        plt.bar(plot_df['strike'], plot_df['vanna_exposure'], 
                color=colors, alpha=0.7, width=bar_width)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, 
                    label=f'Current BTC: ${btc_price:,.0f}')
        plt.axhline(0, color='black', linestyle='-', linewidth=0.5)
        
        plt.xlabel('Strike Price ($)', fontsize=12, fontweight='bold')
        plt.ylabel('Vanna Exposure ($)', fontsize=12, fontweight='bold')
        plt.title('BTC Options Vanna Exposure by Strike\n'
                  'Green = Support in IV spike | Red = Resistance in IV spike', 
                  fontsize=14, fontweight='bold')
        plt.legend(fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"\n✓ Chart saved as '{save_path}'")
        
        plt.close()
        return save_path


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
            if row['vanna_exposure'] > 0:
                vanna_type = "SELL on IV rise"
            else:
                vanna_type = "BUY on IV rise"
            print(f"${row['strike']:>7,.0f} | Vanna: ${row['vanna_exposure']:>12,.0f} | {vanna_type}")
        
        calculator.plot_vanna(vanna_df)