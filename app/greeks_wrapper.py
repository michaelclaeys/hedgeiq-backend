"""
Wrapper that calls your existing Greeks code and formats it for caching
"""
import pandas as pd
import numpy as np
from services.deribit_data import DeribitDataFetcher
from services.trading_signals import RawGreeksAnalysis
from services.calculate_max_pain import MaxPainCalculator
from services.calculate_gex import GEXCalculator  # ADD THIS

def fetch_and_calculate_all_data(days_out=30):
    """
    This is the ONE function the scheduler will call.
    It runs ALL your existing code and returns formatted data.
    
    Returns: dictionary with btc_price, greeks, signals, metrics
    """
    
    # Step 1: Initialize your existing classes
    fetcher = DeribitDataFetcher()
    analyzer = RawGreeksAnalysis()
    max_pain_calc = MaxPainCalculator()
    gex_calc = GEXCalculator()  # ADD THIS
    
    # Step 2: Get BTC price (your existing code)
    btc_price = fetcher.get_btc_price()
    
    # Step 3: Get options chain (your existing code)
    options_df = fetcher.get_options_chain(days_out=days_out)
    
    if options_df.empty:
        raise Exception("No options data available from Deribit")
    
    # Step 4: Calculate all Greeks (your existing code)
    greeks_df = analyzer.analyze_key_levels(days_out=days_out)
    
    if greeks_df.empty:
        raise Exception("Greeks calculation returned empty DataFrame")
    
    # Step 4.5: Calculate max pain
    _, max_pain_strike = max_pain_calc.calculate_max_pain(days_out=days_out)
    
    # Step 4.6: Calculate zero GEX strike - ADD THIS BLOCK
    gex_df = gex_calc.calculate_gex(days_out=days_out)
    
    zero_gex_strike = None
    if not gex_df.empty:
        # Filter to relevant strikes near current price
        relevant = gex_df[
            (gex_df['strike'] >= btc_price * 0.85) & 
            (gex_df['strike'] <= btc_price * 1.15)
        ].sort_values('strike')
        
        if not relevant.empty:
            # Find where GEX changes from positive to negative
            for idx in range(len(relevant) - 1):
                current_gex = relevant.iloc[idx]['gex']
                next_gex = relevant.iloc[idx + 1]['gex']
                current_strike = relevant.iloc[idx]['strike']
                next_strike = relevant.iloc[idx + 1]['strike']
                
                # Found the flip from positive (support) to negative (resistance)
                if current_gex > 0 and next_gex < 0:
                    # Zero GEX is at the last positive strike
                    zero_gex_strike = float(current_strike)
                    break
                # Found flip from negative to positive
                elif current_gex < 0 and next_gex > 0:
                    # Zero GEX is at this positive strike
                    zero_gex_strike = float(next_strike)
                    break
            
            # Fallback: if no flip found, use strike closest to spot
            if zero_gex_strike is None:
                # Find strike closest to current price
                relevant['distance_from_spot'] = abs(relevant['strike'] - btc_price)
                closest_idx = relevant['distance_from_spot'].idxmin()
                zero_gex_strike = float(relevant.loc[closest_idx, 'strike'])
    
    # Step 5: Extract top 10 signals for the dashboard
    greeks_df['Abs_GEX'] = greeks_df.get('GEX', 0).abs()
    signals_df = greeks_df.nlargest(10, 'Abs_GEX')
    
    # Step 6: Format signals as list of dictionaries (for JSON)
    signals = []
    for idx, row in signals_df.iterrows():
        strike = row.get('Strike', 0)
        gex = row.get('GEX', 0)
        vanna = row.get('Vanna', 0)
        charm = row.get('Charm', 0)
        oi = row.get('Open_Interest', 0)
        volume = row.get('Volume', 0)
        
        # Calculate distance from current price
        distance_pct = ((strike - btc_price) / btc_price) * 100
        
        # Determine if support or resistance
        level_type = "support" if gex > 0 else "resistance"
        
        # Get dealer scores
        gex_score = row.get('GEX_Dealer_Score', 0)
        
        signals.append({
            "strike": float(strike),
            "type": level_type,
            "gex": float(gex),
            "vanna": float(vanna),
            "charm": float(charm),
            "open_interest": float(oi),
            "volume": float(volume),
            "distance_pct": float(distance_pct),
            "gex_score": float(gex_score)
        })
    
    # Step 7: Calculate summary metrics - ADD zero_gex_strike
    metrics = {
        "net_gex": float(greeks_df.get('GEX', 0).sum()),
        "net_vanna": float(greeks_df.get('Vanna', 0).sum()),
        "net_charm": float(greeks_df.get('Charm', 0).sum()),
        "max_pain": float(max_pain_strike),
        "zero_gex_strike": zero_gex_strike,  # ADD THIS LINE
        "total_oi": float(greeks_df.get('Open_Interest', 0).sum()),
        "total_volume": float(greeks_df.get('Volume', 0).sum())
    }
    
    # Step 8: Return everything as a dictionary
    return {
        "btc_price": float(btc_price),
        "signals": signals,  # Top 10 only
        "metrics": metrics
    }