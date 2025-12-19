"""
Max Pain Calculator for BTC Options
Max Pain = strike where option holders lose most money
"""

import numpy as np
import pandas as pd
from deribit_data import DeribitDataFetcher

class MaxPainCalculator:
    def __init__(self):
        self.fetcher = DeribitDataFetcher()
    
    def calculate_max_pain(self, days_out=30):
        """
        Calculate Max Pain for BTC options
        Returns: DataFrame with pain by strike, max pain strike
        """
        print("\n" + "=" * 60)
        print("CALCULATING MAX PAIN")
        print("=" * 60)
        
        # Fetch options data
        df = self.fetcher.get_options_chain(days_out=days_out)
        
        if df.empty:
            print("ERROR: No options data fetched!")
            return pd.DataFrame(), 0
        
        print(f"\nAnalyzing {len(df)} options...")
        
        # Get current BTC price
        btc_price = df['underlying_price'].iloc[0]
        
        # Get all unique strikes
        strikes = sorted(df['strike'].unique())
        
        pain_data = []
        
        for test_strike in strikes:
            # Calculate total loss for option holders at this strike
            call_loss = 0
            put_loss = 0
            total_oi = 0
            total_volume = 0
            
            for idx, row in df.iterrows():
                strike = row['strike']
                oi = row['open_interest']
                volume = row['volume']
                option_type = row['option_type']
                
                if option_type == 'call':
                    # Call buyers lose premium if strike > test_strike
                    if test_strike >= strike:
                        call_loss += oi * (test_strike - strike)
                else:
                    # Put buyers lose premium if strike < test_strike
                    if test_strike <= strike:
                        put_loss += oi * (strike - test_strike)
                
                total_oi += oi
                total_volume += volume
            
            total_pain = call_loss + put_loss
            
            pain_data.append({
                'strike': test_strike,
                'call_value': call_loss,
                'put_value': put_loss,
                'total_pain': total_pain,
                'open_interest': total_oi / len(df),  # Average
                'volume': total_volume / len(df)  # Average
            })
        
        pain_df = pd.DataFrame(pain_data)
        
        # Find max pain strike (where total pain is MINIMUM)
        max_pain_strike = pain_df.loc[pain_df['total_pain'].idxmin(), 'strike']
        
        print("\n" + "-" * 60)
        print("MAX PAIN ANALYSIS RESULTS")
        print("-" * 60)
        print(f"\nCurrent BTC Price: ${btc_price:,.2f}")
        print(f"Max Pain Strike: ${max_pain_strike:,.0f}")
        print("=" * 60)
        
        return pain_df, max_pain_strike

if __name__ == "__main__":
    calculator = MaxPainCalculator()
    pain_df, max_pain = calculator.calculate_max_pain(days_out=30)
    
    if not pain_df.empty:
        print(f"\nMax Pain Strike: ${max_pain:,.0f}")
        
        # Show top 5 pain levels
        print("\n" + "-" * 60)
        print("TOP 5 STRIKES BY PAIN (Lowest Pain = Max Pain)")
        print("-" * 60)
        top_pain = pain_df.nsmallest(5, 'total_pain')
        
        for idx, row in top_pain.iterrows():
            print(f"${row['strike']:>7,.0f} | Pain: ${row['total_pain']:>15,.0f}")