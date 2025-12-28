"""
Flow-Based GEX Calculator
Uses actual dealer inventory from trade flow instead of OI assumptions.

This replaces your old calculate_gex.py which assumed:
- Dealers are ALWAYS short calls
- Dealers are ALWAYS long puts

This new version uses ACTUAL dealer positions from the WebSocket trade stream.
"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class GEXResult:
    """Container for GEX calculation results"""
    gex_by_strike: pd.DataFrame
    net_gex: float
    flip_level: Optional[float]
    max_support: Tuple[float, float]  # (strike, gex)
    max_resistance: Tuple[float, float]  # (strike, gex)
    btc_price: float
    timestamp: datetime


class FlowBasedGEXCalculator:
    """
    Calculate GEX using actual dealer inventory from trade flow.
    
    Key difference from old approach:
    - OLD: Assume dealer position based on call/put type
    - NEW: Use ACTUAL dealer position from WebSocket trades
    
    GEX Formula (per 1% move, matching Laevitas):
    GEX = Gamma × DealerPosition × Spot² × 0.01
    
    Where DealerPosition is:
    - POSITIVE if dealer is LONG (bought from retail)
    - NEGATIVE if dealer is SHORT (sold to retail)
    
    The SIGN of GEX tells you:
    - POSITIVE GEX at strike = Dealers LONG gamma = They sell rallies, buy dips = STABILIZING
    - NEGATIVE GEX at strike = Dealers SHORT gamma = They buy rallies, sell dips = AMPLIFYING
    """
    
    def __init__(self, debug: bool = False):
        self.debug = debug
    
    def black_scholes_gamma(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """
        Calculate Black-Scholes Gamma.
        
        Gamma is ALWAYS positive (both calls and puts).
        The SIGN of GEX comes from dealer POSITION, not option type.
        """
        if T <= 0 or sigma <= 0:
            return 0.0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        return gamma
    
    def calculate_gex(
        self,
        dealer_inventory: Dict[int, Dict[str, float]],
        options_data: pd.DataFrame,
        btc_price: float
    ) -> GEXResult:
        """
        Calculate GEX using actual dealer inventory.
        
        Args:
            dealer_inventory: Dict of {strike: {"call": position, "put": position}}
                              Positive = dealer LONG, Negative = dealer SHORT
            options_data: DataFrame with columns: strike, option_type, expiration, mark_iv
            btc_price: Current BTC price
            
        Returns:
            GEXResult with all calculated values
        """
        gex_data = []
        
        if self.debug:
            print("\n=== DEBUG: Inventory received ===")
            for strike, positions in sorted(dealer_inventory.items()):
                if abs(positions.get('call', 0)) > 0.01 or abs(positions.get('put', 0)) > 0.01:
                    print(f"  {strike}: call={positions.get('call', 0):.1f}, put={positions.get('put', 0):.1f}")
        
        # ================================================================
        # FIX: Only use NEAREST expiry per strike/type combo
        # ================================================================
        # The bootstrap seeds inventory for ONE expiry. If we sum across
        # all expiries, we multiply the GEX by ~7x (once per expiry).
        # Instead, use only the nearest expiry which has the highest gamma.
        # ================================================================
        
        options_filtered = options_data.copy()
        
        # Calculate DTE
        options_filtered['dte_seconds'] = (
            options_filtered['expiration'] - pd.Timestamp.now()
        ).dt.total_seconds()
        options_filtered['dte_days'] = options_filtered['dte_seconds'] / 86400
        
        # Filter out expired or nearly expired options (< 2 hours)
        options_filtered = options_filtered[options_filtered['dte_days'] > 0.083]
        
        if options_filtered.empty:
            if self.debug:
                print("=== DEBUG: No valid options after filtering ===")
            return GEXResult(
                gex_by_strike=pd.DataFrame(),
                net_gex=0,
                flip_level=None,
                max_support=(0, 0),
                max_resistance=(0, 0),
                btc_price=btc_price,
                timestamp=datetime.now()
            )
        
        # Sort by DTE and keep only the NEAREST expiry per strike/type
        options_filtered = options_filtered.sort_values('dte_days')
        options_filtered = options_filtered.groupby(['strike', 'option_type']).first().reset_index()
        
        if self.debug:
            print(f"\n=== DEBUG: Using {len(options_filtered)} options (nearest expiry per strike/type) ===")
        
        for _, row in options_filtered.iterrows():
            strike = int(row['strike'])
            option_type = row['option_type']
            
            # Get dealer position at this strike
            if strike in dealer_inventory:
                dealer_position = dealer_inventory[strike].get(option_type, 0)
            else:
                dealer_position = 0
            
            # Skip if no dealer position
            if abs(dealer_position) < 0.001:
                continue
            
            # Time to expiry in years
            T = row['dte_days'] / 365.25
            
            # Get IV (convert from percentage if needed)
            sigma = row['mark_iv']
            if sigma > 5:  # Likely percentage
                sigma = sigma / 100.0
            
            if sigma <= 0:
                continue
            
            # Calculate gamma (always positive)
            gamma = self.black_scholes_gamma(btc_price, strike, T, 0.0, sigma)
            
            # ================================================================
            # THE KEY FORMULA - FLOW-BASED GEX (per 1% move)
            # ================================================================
            # GEX = Gamma × DealerPosition × Spot² × 0.01
            #
            # This matches Laevitas "USD GEX per 1% move" convention.
            # ================================================================
            
            gex = gamma * dealer_position * (btc_price ** 2) * 0.01
            
            # Time weight: near-term options matter more
            days_to_expiry = row['dte_days']
            if days_to_expiry > 0:
                time_weight = 1.0 / np.sqrt(days_to_expiry)
            else:
                time_weight = 1.0
            
            gex_weighted = gex * time_weight
            
            if self.debug:
                print(f"  {strike} {option_type}: pos={dealer_position:.1f}, "
                      f"gamma={gamma:.8f}, gex=${gex:,.0f}, "
                      f"weighted=${gex_weighted:,.0f}, DTE={days_to_expiry:.1f}d")
            
            gex_data.append({
                'strike': strike,
                'option_type': option_type,
                'dealer_position': dealer_position,
                'gamma': gamma,
                'gex_raw': gex,
                'gex_weighted': gex_weighted,
                'time_weight': time_weight,
                'days_to_expiry': days_to_expiry,
                'mark_iv': row['mark_iv']
            })
        
        if not gex_data:
            if self.debug:
                print("=== DEBUG: No GEX data generated! ===")
            return GEXResult(
                gex_by_strike=pd.DataFrame(),
                net_gex=0,
                flip_level=None,
                max_support=(0, 0),
                max_resistance=(0, 0),
                btc_price=btc_price,
                timestamp=datetime.now()
            )
        
        gex_df = pd.DataFrame(gex_data)
        
        # Aggregate by strike (sum calls + puts)
        gex_by_strike = gex_df.groupby('strike').agg({
            'gex_weighted': 'sum',
            'gex_raw': 'sum',
            'dealer_position': 'sum'
        }).reset_index()
        
        gex_by_strike = gex_by_strike.rename(columns={'gex_weighted': 'gex'})
        gex_by_strike = gex_by_strike.sort_values('strike')
        
        # Calculate key levels
        net_gex = gex_by_strike['gex'].sum()
        
        if self.debug:
            print("\n=== DEBUG: GEX by strike (aggregated) ===")
            for _, row in gex_by_strike.iterrows():
                level_type = "SUPPORT" if row['gex'] > 0 else "RESIST"
                print(f"  ${int(row['strike']):,}: GEX=${row['gex']:,.0f} ({level_type})")
            print(f"\n  NET GEX: ${net_gex:,.0f}")
            print("=" * 40)
        
        # Max support (most positive GEX)
        if len(gex_by_strike[gex_by_strike['gex'] > 0]) > 0:
            max_support_row = gex_by_strike.loc[gex_by_strike['gex'].idxmax()]
            max_support = (max_support_row['strike'], max_support_row['gex'])
        else:
            max_support = (0, 0)
        
        # Max resistance (most negative GEX)
        if len(gex_by_strike[gex_by_strike['gex'] < 0]) > 0:
            max_resistance_row = gex_by_strike.loc[gex_by_strike['gex'].idxmin()]
            max_resistance = (max_resistance_row['strike'], max_resistance_row['gex'])
        else:
            max_resistance = (0, 0)
        
        # Find flip level (where GEX crosses zero)
        flip_level = self._find_flip_level(gex_by_strike, btc_price)
        
        return GEXResult(
            gex_by_strike=gex_by_strike,
            net_gex=net_gex,
            flip_level=flip_level,
            max_support=max_support,
            max_resistance=max_resistance,
            btc_price=btc_price,
            timestamp=datetime.now()
        )
    
    def _find_flip_level(self, gex_df: pd.DataFrame, btc_price: float) -> Optional[float]:
        """
        Find the strike where GEX flips from positive to negative (or vice versa).
        This is the "zero gamma" level - below it one regime, above it another.
        """
        # Filter to relevant range around spot
        relevant = gex_df[
            (gex_df['strike'] >= btc_price * 0.85) &
            (gex_df['strike'] <= btc_price * 1.15)
        ].copy().sort_values('strike')
        
        if len(relevant) < 2:
            return None
        
        # Look for sign flip
        for i in range(len(relevant) - 1):
            current = relevant.iloc[i]
            next_row = relevant.iloc[i + 1]
            
            if current['gex'] > 0 and next_row['gex'] < 0:
                # Flip from positive to negative - interpolate
                ratio = current['gex'] / (current['gex'] - next_row['gex'])
                flip = current['strike'] + ratio * (next_row['strike'] - current['strike'])
                return flip
            elif current['gex'] < 0 and next_row['gex'] > 0:
                # Flip from negative to positive
                ratio = -current['gex'] / (next_row['gex'] - current['gex'])
                flip = current['strike'] + ratio * (next_row['strike'] - current['strike'])
                return flip
        
        return None
    
    def format_result(self, result: GEXResult) -> str:
        """Format GEX result for display"""
        lines = [
            "\n" + "=" * 60,
            "FLOW-BASED GEX ANALYSIS",
            "=" * 60,
            f"\nBTC Price: ${result.btc_price:,.2f}",
            f"Timestamp: {result.timestamp}",
            f"\nNet GEX: ${result.net_gex:,.0f}",
        ]
        
        if result.net_gex > 0:
            lines.append("  → POSITIVE GAMMA: Dealers stabilize (mean reversion likely)")
        else:
            lines.append("  → NEGATIVE GAMMA: Dealers amplify (trend continuation likely)")
        
        if result.flip_level:
            distance = ((result.flip_level - result.btc_price) / result.btc_price) * 100
            lines.append(f"\nFlip Level: ${result.flip_level:,.0f} ({distance:+.2f}% from spot)")
            if result.btc_price > result.flip_level:
                lines.append("  → Price ABOVE flip = Positive gamma regime")
            else:
                lines.append("  → Price BELOW flip = Negative gamma regime")
        
        lines.append(f"\nMax Support: ${result.max_support[0]:,.0f} (GEX: ${result.max_support[1]:,.0f})")
        lines.append(f"Max Resistance: ${result.max_resistance[0]:,.0f} (GEX: ${result.max_resistance[1]:,.0f})")
        
        lines.append("\n" + "-" * 60)
        lines.append("TOP STRIKES BY GEX")
        lines.append("-" * 60)
        
        if not result.gex_by_strike.empty:
            top = result.gex_by_strike.copy()
            top['abs_gex'] = top['gex'].abs()
            top = top.nlargest(10, 'abs_gex')
            
            for _, row in top.iterrows():
                level_type = "SUPPORT" if row['gex'] > 0 else "RESISTANCE"
                lines.append(f"${row['strike']:>8,.0f} | GEX: ${row['gex']:>12,.0f} | {level_type}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


# ============================================================
# BOOTSTRAP: Initialize dealer inventory from current OI
# ============================================================

def bootstrap_inventory_from_oi(options_df: pd.DataFrame, method: str = "neutral") -> Dict[int, Dict[str, float]]:
    """
    Bootstrap initial dealer inventory from Open Interest.
    
    Methods:
    - "neutral": Assume 50% of OI is dealer long, 50% short = net zero per strike
    - "traditional": Assume dealers short calls, long puts (your old approach)
    - "zero": Start with zero inventory, build from trades only
    
    For the most accurate results, use "zero" and wait for WebSocket to warm up.
    """
    inventory = {}
    
    for _, row in options_df.iterrows():
        strike = int(row['strike'])
        option_type = row['option_type']
        oi = row['open_interest']
        
        if strike not in inventory:
            inventory[strike] = {"call": 0.0, "put": 0.0}
        
        if method == "zero":
            # Start empty, build from trades
            pass
        elif method == "neutral":
            # Assume net neutral - no directional bias
            inventory[strike][option_type] = 0.0
        elif method == "traditional":
            # Old assumption: dealers short calls, short puts
            # (This is what Laevitas does as a baseline)
            inventory[strike][option_type] = -oi  # Dealer short
    
    return inventory


if __name__ == "__main__":
    # Demo: Show how the calculator works with mock data
    
    calculator = FlowBasedGEXCalculator(debug=True)
    
    # Mock dealer inventory matching bootstrap values
    mock_inventory = {
        75000: {"call": 0.0, "put": 2958.0},     # Long puts = positive GEX
        80000: {"call": 0.0, "put": -3695.0},    # Short puts = negative GEX
        85000: {"call": 0.0, "put": -61.0},      # Short puts = negative GEX
        90000: {"call": 146.0, "put": 0.0},      # Long calls = positive GEX
        95000: {"call": 193.0, "put": 0.0},      # Long calls = positive GEX
        100000: {"call": 1143.0, "put": 0.0},    # Long calls = positive GEX
    }
    
    # Mock options data - ONE expiry per strike
    mock_options = pd.DataFrame([
        {"strike": 75000, "option_type": "put", "expiration": pd.Timestamp.now() + pd.Timedelta(days=4), "mark_iv": 60},
        {"strike": 80000, "option_type": "put", "expiration": pd.Timestamp.now() + pd.Timedelta(days=1), "mark_iv": 53},
        {"strike": 85000, "option_type": "put", "expiration": pd.Timestamp.now() + pd.Timedelta(days=1), "mark_iv": 37},
        {"strike": 90000, "option_type": "call", "expiration": pd.Timestamp.now() + pd.Timedelta(days=1), "mark_iv": 34},
        {"strike": 95000, "option_type": "call", "expiration": pd.Timestamp.now() + pd.Timedelta(days=4), "mark_iv": 40},
        {"strike": 100000, "option_type": "call", "expiration": pd.Timestamp.now() + pd.Timedelta(days=4), "mark_iv": 50},
    ])
    
    result = calculator.calculate_gex(
        dealer_inventory=mock_inventory,
        options_data=mock_options,
        btc_price=87800
    )
    
    print(calculator.format_result(result))