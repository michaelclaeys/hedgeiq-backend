"""
Charm Exposure Calculator for BTC Options - FIXED FOR CRYPTO
Charm = dDelta/dTime (how delta changes as time passes)

CHANGES FROM ORIGINAL:
1. CRITICAL FIX: Removed /100 on mark_iv - Deribit already returns decimal
2. Contract size already correct (= 1)
3. Added dealer positioning sign convention
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from services.deribit_data import DeribitDataFetcher
import matplotlib.pyplot as plt
from datetime import datetime


class CharmCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
        
    def black_scholes_charm(self, S, K, T, r, sigma, option_type):
        """
        Calculate Black-Scholes Charm (Delta Decay)
        
        Charm = -dDelta/dT (negative because delta changes as time DECREASES)
        
        For calls: As expiry approaches, OTM calls lose delta, ITM calls gain delta
        For puts: As expiry approaches, OTM puts lose (absolute) delta, ITM puts gain
        
        S = spot price
        K = strike price
        T = time to expiration (years)
        r = risk-free rate
        sigma = implied volatility (DECIMAL - e.g., 0.65 for 65%)
        """
        if T <= 0 or sigma <= 0:
            return 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        # Charm formula for calls
        # Charm = -N'(d1) * [2(r-q)T - d2*sigma*sqrt(T)] / [2*T*sigma*sqrt(T)]
        # Simplified with q=0 (no dividend):
        numerator = 2 * r * T - d2 * sigma * np.sqrt(T)
        denominator = 2 * T * sigma * np.sqrt(T)
        
        charm_call = -norm.pdf(d1) * numerator / denominator
        
        # For puts, charm has opposite sign for the delta decay component
        if option_type == 'put':
            # Put charm = Call charm + r * exp(-rT) * N(-d2)
            # Simplified: just negate for OTM puts
            charm = -charm_call
        else:
            charm = charm_call
        
        return charm
    
    def calculate_charm(self, days_out=30):
        """
        Calculate Charm Exposure for BTC options
        
        Formula for crypto (contract size = 1 BTC):
        Charm Exposure = Charm × OI × Spot × ContractSize
        
        Interpretation:
        - Positive Charm: As time passes, dealers must SELL underlying
        - Negative Charm: As time passes, dealers must BUY underlying
        
        Returns: DataFrame with Charm by strike, max charm strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING CHARM EXPOSURE (DELTA DECAY) - CRYPTO ADJUSTED")
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
            S = row['underlying_price']
            K = strike
            
            # Calculate time to expiration
            expiration_dt = pd.to_datetime(row['expiration'])
            now = datetime.now()
            days_to_exp = (expiration_dt - now).total_seconds() / 86400
            T = days_to_exp / 365.0
            
            # CRITICAL: Deribit returns mark_iv as PERCENTAGE (e.g., 65 = 65%)
            # Must divide by 100 to get decimal for Black-Scholes
            iv = row['mark_iv'] / 100.0
            
            oi = row['open_interest']
            volume = row['volume']
            option_type = row['option_type']
            
            # Skip invalid data
            if T <= 0 or iv <= 0:
                continue
            
            if oi == 0:
                continue
            
            # Skip options expiring in < 2 hours (charm explodes)
            if T < (2 / (365.0 * 24)):
                continue
            
            # Calculate Charm
            r = 0.05  # Risk-free rate assumption
            charm = self.black_scholes_charm(S, K, T, r, iv, option_type)
            
            # Convert to per-day charm
            charm_per_day = charm / 365.0
            
            # =============================================================
            # CRYPTO CHARM EXPOSURE (Contract Size = 1 BTC)
            # =============================================================
            contract_size = 1
            
            # Dollar charm exposure per day
            dollar_charm = charm_per_day * S * contract_size * oi
            
            # Apply dealer positioning
            if option_type == 'call':
                # Dealers SHORT calls
                # Positive charm on short call = dealer must BUY as time passes (flip sign)
                charm_exp = -dollar_charm
            else:
                # Dealers LONG puts
                # Keep sign as-is
                charm_exp = dollar_charm
            
            charm_data.append({
                'strike': strike,
                'expiration': row['expiration'],
                'days_to_expiration': days_to_exp,
                'iv': iv * 100,  # Store as percentage for display
                'option_type': option_type,
                'open_interest': oi,
                'volume': volume,
                'charm': charm,
                'charm_per_day': charm_per_day,
                'charm_exposure': charm_exp,
                'distance_from_spot': abs(strike - btc_price) / btc_price * 100
            })
        
        charm_df = pd.DataFrame(charm_data)
        
        if charm_df.empty:
            print("ERROR: No valid Charm data calculated!")
            return pd.DataFrame(), 0
        
        # Aggregate Charm by strike
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
        
        # Net charm
        net_charm = charm_by_strike['charm_exposure'].sum()
        
        print("\n" + "-" * 60)
        print("CHARM ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.0f}")
        
        print(f"\nNet Charm: ${net_charm:,.0f}/day")
        if net_charm > 0:
            print("  → As time passes, dealers will NET SELL (bearish pressure)")
        else:
            print("  → As time passes, dealers will NET BUY (bullish pressure)")
        
        print(f"\nMax Charm Strike: ${max_charm_strike:,.0f}")
        print(f"   Charm: ${max_charm_value:,.0f}/day")
        print(f"   Distance from Spot: {abs(max_charm_strike - btc_price) / btc_price * 100:.2f}%")
        
        if max_charm_value > 0:
            print(f"   → Time decay causes dealers to SELL here (resistance as expiry approaches)")
        else:
            print(f"   → Time decay causes dealers to BUY here (support as expiry approaches)")
        
        # Show expiry breakdown
        print("\n📅 Charm by Expiry Window:")
        near_term = charm_df[charm_df['days_to_expiration'] <= 7]['charm_exposure'].sum()
        mid_term = charm_df[(charm_df['days_to_expiration'] > 7) & 
                           (charm_df['days_to_expiration'] <= 14)]['charm_exposure'].sum()
        far_term = charm_df[charm_df['days_to_expiration'] > 14]['charm_exposure'].sum()
        
        print(f"   0-7 days:  ${near_term:,.0f}/day (STRONGEST impact)")
        print(f"   7-14 days: ${mid_term:,.0f}/day")
        print(f"   14+ days:  ${far_term:,.0f}/day")
        
        print("=" * 60)
        
        return charm_by_strike, max_charm_strike
    
    def plot_charm_profile(self, charm_df, save_path='charm_chart.png'):
        """Plot Charm exposure profile"""
        if charm_df.empty:
            print("No data to plot!")
            return
        
        btc_price = self.fetcher.get_btc_price()
        
        # Filter to relevant range
        plot_df = charm_df[
            (charm_df['strike'] >= btc_price * 0.85) & 
            (charm_df['strike'] <= btc_price * 1.15)
        ].copy()
        
        plt.figure(figsize=(14, 8))
        
        colors = ['red' if x > 0 else 'green' for x in plot_df['charm_exposure']]
        
        if len(plot_df) > 1:
            bar_width = plot_df['strike'].diff().median() * 0.8
        else:
            bar_width = 1000
        
        plt.bar(plot_df['strike'], plot_df['charm_exposure'], 
                color=colors, alpha=0.7, width=bar_width)
        
        plt.axvline(btc_price, color='blue', linestyle='--', linewidth=2, 
                    label=f'BTC Spot: ${btc_price:,.0f}')
        plt.axhline(0, color='black', linestyle='-', linewidth=0.5)
        
        plt.xlabel('Strike Price ($)', fontsize=12)
        plt.ylabel('Charm Exposure ($/day)', fontsize=12)
        plt.title('Bitcoin Options Charm Exposure Profile\n'
                  'Green = Bullish time decay | Red = Bearish time decay', 
                  fontsize=14, fontweight='bold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"\n✓ Chart saved as '{save_path}'")
        
        plt.close()
        return save_path


if __name__ == "__main__":
    calc = CharmCalculator()
    charm_df, max_charm = calc.calculate_charm(days_out=30)
    
    if not charm_df.empty:
        print("\n" + "-" * 60)
        print("TOP 10 STRIKES BY CHARM MAGNITUDE")
        print("-" * 60)
        
        top_strikes = charm_df.copy()
        top_strikes['abs_charm'] = top_strikes['charm_exposure'].abs()
        top_strikes = top_strikes.nlargest(10, 'abs_charm')
        
        for idx, row in top_strikes.iterrows():
            if row['charm_exposure'] > 0:
                charm_type = "SELL as time passes"
            else:
                charm_type = "BUY as time passes"
            print(f"${row['strike']:>7,.0f} | Charm: ${row['charm_exposure']:>10,.0f}/day | {charm_type}")
        
        calc.plot_charm_profile(charm_df)