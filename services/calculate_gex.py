"""
Gamma Exposure (GEX) Calculator for BTC Options - FIXED FOR CRYPTO
Calculates dealer gamma exposure at each strike

CHANGES FROM ORIGINAL:
1. Removed /100 equity multiplier (crypto contract size = 1 BTC)
2. Added proper dollar gamma calculation
3. Kept sign convention: Calls = negative (dealers short), Puts = positive (dealers long)
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from services.deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt


class GEXCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_gamma(self, S, K, T, r, sigma):
        """
        Calculate Black-Scholes Gamma
        
        S = spot price
        K = strike price
        T = time to expiration (years)
        r = risk-free rate
        sigma = implied volatility (decimal, e.g., 0.65 for 65%)
        
        Returns: Gamma (change in delta per $1 move in underlying)
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        return gamma
    
    def calculate_gex(self, days_out=30):
        """
        Calculate Gamma Exposure for BTC options
        
        Formula for crypto (contract size = 1 BTC):
        GEX = Gamma × OI × Spot × ContractSize
        
        Where ContractSize = 1 for Deribit BTC options
        
        Sign Convention (SpotGamma standard):
        - Calls = NEGATIVE GEX (dealers are short calls → short gamma)
        - Puts = POSITIVE GEX (dealers are long puts from selling → long gamma)
        
        Returns: DataFrame with GEX by strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING GAMMA EXPOSURE (GEX) - CRYPTO ADJUSTED")
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
            r = 0.0  # Risk-free rate (can adjust if needed)
            # CRITICAL: Deribit returns mark_iv as PERCENTAGE (e.g., 65 = 65%)
            # Must divide by 100 to get decimal for Black-Scholes
            sigma = row['mark_iv'] / 100.0
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            # Skip invalid data
            if sigma <= 0 or T <= 0 or oi == 0:
                continue
            
            # Skip options expiring in < 2 hours (gamma explodes)
            if T < (2 / (365.25 * 24)):
                continue
            
            # Calculate gamma
            gamma = self.black_scholes_gamma(S, K, T, r, sigma)
            
            # =============================================================
            # CRYPTO GEX FORMULA (Contract Size = 1 BTC)
            # =============================================================
            # Dollar Gamma = Gamma × Spot × ContractSize × OI
            # 
            # This gives you: "$ of BTC dealers must trade per $1 move"
            #
            # For "per 1% move" interpretation, multiply by S/100:
            # GEX_pct = Gamma × S × 1 × OI × (S/100) = Gamma × S² × OI / 100
            #
            # But for crypto with ContractSize=1, we simplify to:
            # GEX = Gamma × S × OI
            # =============================================================
            
            contract_size = 1  # Deribit BTC options = 1 BTC per contract
            
            # Raw dollar gamma exposure
            dollar_gamma = gamma * S * contract_size * oi
            
            # Apply dealer positioning sign convention
            if option_type == 'call':
                # Dealers are SHORT calls (retail/funds buy calls)
                # Short gamma = dealers must buy when price rises, sell when falls
                gex = -dollar_gamma
            else:
                # Dealers are LONG puts (they sold puts to retail/funds)
                # Long gamma = dealers sell when price rises, buy when falls
                gex = dollar_gamma
            
            gex_data.append({
                'strike': K,
                'option_type': option_type,
                'expiration': row['expiration'],
                'gamma': gamma,
                'open_interest': oi,
                'volume': volume,
                'gex': gex,
                'mark_iv': row['mark_iv'],  # Keep as percentage for display
                'mark_price': row['mark_price']
            })
        
        gex_df = pd.DataFrame(gex_data)
        
        if gex_df.empty:
            print("ERROR: No valid GEX data calculated!")
            return pd.DataFrame()
        
        # Aggregate GEX by strike (sum calls + puts at each strike)
        gex_by_strike = gex_df.groupby('strike').agg({
            'gex': 'sum',
            'open_interest': 'sum',
            'volume': 'sum'
        }).reset_index()
        
        gex_by_strike = gex_by_strike.sort_values('strike')
        
        # Find key levels
        max_negative_idx = gex_by_strike['gex'].idxmin()
        max_positive_idx = gex_by_strike['gex'].idxmax()
        
        max_negative_gex = gex_by_strike.loc[max_negative_idx]
        max_positive_gex = gex_by_strike.loc[max_positive_idx]
        
        # Find Zero GEX level (where sign flips)
        relevant_gex = gex_by_strike[
            (gex_by_strike['strike'] >= btc_price * 0.85) & 
            (gex_by_strike['strike'] <= btc_price * 1.15)
        ].copy().sort_values('strike')
        
        zero_gex_strike = None
        if len(relevant_gex) > 1:
            for i in range(len(relevant_gex) - 1):
                current = relevant_gex.iloc[i]
                next_row = relevant_gex.iloc[i + 1]
                
                # Flip from positive to negative
                if current['gex'] > 0 and next_row['gex'] < 0:
                    zero_gex_strike = current['strike']
                    break
                # Flip from negative to positive
                elif current['gex'] < 0 and next_row['gex'] > 0:
                    zero_gex_strike = next_row['strike']
                    break
        
        # Calculate net GEX (market regime indicator)
        net_gex = gex_by_strike['gex'].sum()
        
        print("\n" + "-" * 60)
        print("GEX ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.2f}")
        print(f"\nNet GEX: ${net_gex:,.0f}")
        if net_gex > 0:
            print("  → POSITIVE GAMMA ENVIRONMENT (mean reversion, dealers stabilize)")
        else:
            print("  → NEGATIVE GAMMA ENVIRONMENT (trend continuation, dealers amplify)")
        
        print(f"\nMax NEGATIVE GEX (Resistance): ${max_negative_gex['strike']:,.0f}")
        print(f"   GEX: ${max_negative_gex['gex']:,.0f}")
        
        print(f"\nMax POSITIVE GEX (Support): ${max_positive_gex['strike']:,.0f}")
        print(f"   GEX: ${max_positive_gex['gex']:,.0f}")
        
        if zero_gex_strike:
            print(f"\nZero GEX (Flip Level): ${zero_gex_strike:,.0f}")
            distance = ((zero_gex_strike - btc_price) / btc_price) * 100
            print(f"   Distance from spot: {distance:+.2f}%")
        else:
            print("\nZero GEX: Not found in ±15% range")
        
        print("=" * 60)
        
        return gex_by_strike
    
    def plot_gex(self, gex_df, save_path='gex_chart.png'):
        """Plot GEX by strike"""
        if gex_df.empty:
            print("No data to plot!")
            return
        
        btc_price = self.fetcher.get_btc_price()
        
        # Filter to relevant range for cleaner chart
        plot_df = gex_df[
            (gex_df['strike'] >= btc_price * 0.85) & 
            (gex_df['strike'] <= btc_price * 1.15)
        ].copy()
        
        plt.figure(figsize=(14, 8))
        
        colors = ['red' if x < 0 else 'green' for x in plot_df['gex']]
        
        # Calculate bar width based on strike spacing
        if len(plot_df) > 1:
            bar_width = plot_df['strike'].diff().median() * 0.8
        else:
            bar_width = 1000
        
        plt.bar(plot_df['strike'], plot_df['gex'], color=colors, alpha=0.7, width=bar_width)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, 
                    label=f'Current BTC: ${btc_price:,.0f}')
        plt.axhline(0, color='black', linestyle='-', linewidth=0.5)
        
        plt.xlabel('Strike Price ($)', fontsize=12, fontweight='bold')
        plt.ylabel('Gamma Exposure ($)', fontsize=12, fontweight='bold')
        plt.title('BTC Options Gamma Exposure (GEX) by Strike\n'
                  'Green = Support (dealers buy dips) | Red = Resistance (dealers sell rallies)', 
                  fontsize=14, fontweight='bold')
        plt.legend(fontsize=10)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"\n✓ Chart saved as '{save_path}'")
        
        plt.close()
        return save_path


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
            gex_type = "RESISTANCE" if row['gex'] < 0 else "SUPPORT"
            print(f"${row['strike']:>7,.0f} | GEX: ${row['gex']:>12,.0f} | OI: {row['open_interest']:>8,.0f} | {gex_type}")
        
        calculator.plot_gex(gex_df)