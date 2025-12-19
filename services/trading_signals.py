"""
Raw Greeks Analysis with Improved Dealer Scores
No automated signals - you analyze the data yourself

IMPROVEMENTS v2:
- Simplified dealer score (removed vol/OI from score calculation)
- Vol/OI shown separately for manual interpretation
- Round number weighting adjusted (5k = 1.5, 1k = 0.5)
- Score scale: 0-4 (instead of 0-5)
- Clearer output with discretionary guidance

This script shows:
1. GEX + dealer score
2. Vanna + dealer score  
3. Charm + dealer score
4. Max Pain
5. Volume analysis (separate from score)

YOU decide the trade direction based on the Greeks mechanics.
"""

import numpy as np
import pandas as pd
from datetime import datetime
from services.calculate_gex import GEXCalculator
from services.calculate_vanna import VannaCalculator
from services.calculate_charm import CharmCalculator
from services.calculate_max_pain import MaxPainCalculator

class RawGreeksAnalysis:
    def __init__(self):
        self.gex_calc = GEXCalculator()
        self.vanna_calc = VannaCalculator()
        self.charm_calc = CharmCalculator()
        self.max_pain_calc = MaxPainCalculator()
        
    def calculate_dealer_score(self, strike, open_interest, median_oi=100):
        """
        Simplified score 0-4 based on structural positioning likelihood
        
        Scoring:
        - Round number strike (5k) = +1.5
        - Round number strike (1k) = +0.5
        - OI > 2x median = +2
        - OI > median = +1
        
        REMOVED: Volume-based scoring (now shown separately for discretionary interpretation)
        
        Higher score = more dealer structural exposure = more reliable level
        """
        score = 0
        
        # Round number strikes (dealers cluster here)
        if strike % 5000 == 0:
            score += 1.5      # Major round numbers (85k, 90k, 95k, 100k)
        elif strike % 1000 == 0:
            score += 0.5      # Minor round numbers (86k, 87k, 89k, 91k)
        
        # OI significance (vs MEDIAN, not mean)
        if open_interest > 2 * median_oi:
            score += 2        # Very high OI
        elif open_interest > median_oi:
            score += 1        # Above average OI
            
        return min(score, 4)  # Cap at 4
    
    def interpret_vol_oi(self, vol_oi_ratio, gex_value):
        """
        Context-aware vol/OI interpretation
        """
        if vol_oi_ratio > 3:
            if gex_value > 0:
                return "VERY HIGH - Support being challenged/unstable"
            else:
                return "VERY HIGH - Fresh resistance positioning"
        elif vol_oi_ratio > 1.5:
            return "ELEVATED - Active trading at this level"
        elif vol_oi_ratio > 0.5:
            return "MODERATE - Normal activity"
        else:
            if gex_value > 0:
                return "LOW - Stable support (established positions)"
            else:
                return "LOW - Stale resistance (old positions)"
    
    def interpret_gex_mechanics(self, gex_value):
        """
        Explain what GEX means for price action
        """
        if gex_value > 0:
            return "LONG gamma → Price falls = Dealers BUY (support) | Price rises = Dealers SELL (dampens)"
        else:
            return "SHORT gamma → Price rises = Dealers BUY (amplifies) | Price falls = Dealers SELL (accelerates)"
    
    def interpret_vanna_mechanics(self, vanna_value):
        """
        Explain what Vanna means for price action
        """
        if vanna_value > 0:
            return "Positive Vanna → Rising IV = Dealers SELL spot (weakens support) | Falling IV = Dealers BUY (strengthens)"
        else:
            return "Negative Vanna → Rising IV = Dealers BUY spot (strengthens resistance) | Falling IV = Dealers SELL"
    
    def interpret_charm_mechanics(self, charm_value):
        """
        Explain what Charm means for price action
        """
        if charm_value > 0:
            return "Positive Charm → As expiry approaches = Delta decreases = Dealers SELL spot (bearish pressure)"
        else:
            return "Negative Charm → As expiry approaches = Delta increases = Dealers BUY spot (bullish pressure)"
    
    def analyze_key_levels(self, days_out=30):
        """
        Get raw Greeks data for key levels with improved dealer scores
        Returns formatted analysis for manual interpretation
        """
        print("\n" + "="*70)
        print("RAW GREEKS ANALYSIS - DISCRETIONARY MODE v2")
        print("="*70)
        
        # Fetch all Greeks - FIXED: Unpack charm tuple
        print("\n🔄 Fetching Greeks data...")
        gex_df = self.gex_calc.calculate_gex(days_out=days_out)
        vanna_df = self.vanna_calc.calculate_vanna(days_out=days_out)
        charm_df, max_charm_strike = self.charm_calc.calculate_charm(days_out=days_out)
        
        print("🔄 Calculating Max Pain...")
        max_pain_result = self.max_pain_calc.calculate_max_pain(days_out=days_out)
        
        # Handle max pain result
        if isinstance(max_pain_result, tuple):
            pain_df, max_pain_strike = max_pain_result
        else:
            pain_df = max_pain_result
            max_pain_strike = 0
        
        # Standardize column names
        gex_df.columns = gex_df.columns.str.title()
        vanna_df.columns = vanna_df.columns.str.title()
        charm_df.columns = charm_df.columns.str.title()
        pain_df.columns = pain_df.columns.str.title()
        
        # Rename specific columns
        if 'Gex' in gex_df.columns:
            gex_df.rename(columns={'Gex': 'GEX'}, inplace=True)
        if 'Vanna_Exposure' in vanna_df.columns:
            vanna_df.rename(columns={'Vanna_Exposure': 'Vanna'}, inplace=True)
        if 'Charm_Exposure' in charm_df.columns:
            charm_df.rename(columns={'Charm_Exposure': 'Charm'}, inplace=True)
        if 'Open_Interest' not in gex_df.columns and 'Open_interest' in gex_df.columns:
            gex_df.rename(columns={'Open_interest': 'Open_Interest'}, inplace=True)
        if 'Open_Interest' not in vanna_df.columns and 'Open_interest' in vanna_df.columns:
            vanna_df.rename(columns={'Open_interest': 'Open_Interest'}, inplace=True)
        if 'Open_Interest' not in charm_df.columns and 'Open_interest' in charm_df.columns:
            charm_df.rename(columns={'Open_interest': 'Open_Interest'}, inplace=True)
        
        # Get current price
        try:
            import requests
            response = requests.get("https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd")
            data = response.json()
            if 'result' not in data:
                raise Exception("Invalid response from Deribit price API")
            current_price = data['result']['index_price']
        except Exception as e:
            print(f"\n❌ CRITICAL ERROR: Cannot fetch current BTC price!")
            print(f"   Error: {e}")
            print(f"   Cannot proceed with stale data. Exiting.")
            return pd.DataFrame()
        
        print(f"\n💰 Current BTC Price: ${current_price:,.2f}")
        
        # Merge all data
        analysis_df = pd.DataFrame()
        
        for name, df in [('GEX', gex_df), ('Vanna', vanna_df), ('Charm', charm_df), ('MaxPain', pain_df)]:
            if df.empty:
                print(f"⚠️  WARNING: {name} DataFrame is empty, skipping...")
                continue
                
            if 'Strike' not in df.columns:
                print(f"⚠️  WARNING: {name} DataFrame missing 'Strike' column")
                print(f"   Available columns: {df.columns.tolist()}")
                continue
            
            if analysis_df.empty:
                analysis_df = df.copy()
                print(f"✓ Initialized with {name}")
            else:
                print(f"✓ Merging {name}...")
                analysis_df = analysis_df.merge(df, on='Strike', how='outer', suffixes=('', '_dup'))
        
        if analysis_df.empty:
            print("\n❌ ERROR: All DataFrames are empty or missing Strike column!")
            return pd.DataFrame()
        
        # Remove duplicate columns
        analysis_df = analysis_df.loc[:, ~analysis_df.columns.str.endswith('_dup')]
        
        # Fill NaN values
        analysis_df = analysis_df.fillna(0)
        
        # Add Volume column if missing
        if 'Volume' not in analysis_df.columns:
            analysis_df['Volume'] = 0
        
        # Add DTE column if missing
        if 'Dte' in analysis_df.columns and 'DTE' not in analysis_df.columns:
            analysis_df['DTE'] = analysis_df['Dte']
        elif 'DTE' not in analysis_df.columns:
            analysis_df['DTE'] = 7
        
        # Calculate MEDIAN OI for dealer scoring
        median_oi = analysis_df['Open_Interest'].median() if 'Open_Interest' in analysis_df.columns else 100
        
        print(f"\n📊 Using MEDIAN OI as baseline: {median_oi:.0f}")
        
        # Add dealer scores (simplified - no volume component)
        if 'GEX' in analysis_df.columns and 'Open_Interest' in analysis_df.columns:
            analysis_df['GEX_Dealer_Score'] = analysis_df.apply(
                lambda row: self.calculate_dealer_score(
                    row['Strike'],
                    row['Open_Interest'], 
                    median_oi
                ), 
                axis=1
            )
        
        if 'Vanna' in analysis_df.columns:
            analysis_df['Vanna_Dealer_Score'] = analysis_df.apply(
                lambda row: self.calculate_dealer_score(
                    row['Strike'],
                    row.get('Open_Interest', 0), 
                    median_oi
                ), 
                axis=1
            )
        
        if 'Charm' in analysis_df.columns:
            analysis_df['Charm_Dealer_Score'] = analysis_df.apply(
                lambda row: self.calculate_dealer_score(
                    row['Strike'],
                    row.get('Open_Interest', 0), 
                    median_oi
                ), 
                axis=1
            )
        
        # Sort by absolute GEX
        if 'GEX' not in analysis_df.columns:
            print("\n❌ ERROR: No GEX column found after merge!")
            return analysis_df
            
        analysis_df['Abs_GEX'] = analysis_df['GEX'].abs()
        key_levels = analysis_df.nlargest(10, 'Abs_GEX')
        
        # Format output
        output = []
        output.append("\n" + "="*70)
        output.append("KEY LEVELS ANALYSIS")
        output.append("="*70)
        
        for idx, row in key_levels.iterrows():
            strike = row['Strike']
            gex = row['GEX']
            vanna = row.get('Vanna', 0)
            charm = row.get('Charm', 0)
            oi = row.get('Open_Interest', 0)
            volume = row.get('Volume', 0)
            dte = row.get('DTE', 0)
            
            # Distance from current price
            distance_pct = ((strike - current_price) / current_price) * 100
            
            # Level type
            if gex > 0:
                level_type = "SUPPORT"
            else:
                level_type = "RESISTANCE"
            
            # Check if round number
            round_indicator = ""
            if strike % 5000 == 0:
                round_indicator = " [5K ROUND]"
            elif strike % 1000 == 0:
                round_indicator = " [1K ROUND]"
            
            output.append(f"\n{level_type}: ${strike:,.0f}{round_indicator}")
            output.append(f"   Distance: {distance_pct:+.1f}% | Current: ${current_price:,.0f}")
            output.append("")
            
            # GEX Analysis
            gex_score = row.get('GEX_Dealer_Score', 0)
            output.append(f"   GEX: {gex:,.0f} | Dealer Score: {gex_score:.1f}/4")
            output.append(f"      {self.interpret_gex_mechanics(gex)}")
            output.append("")
            
            # Vanna Analysis
            vanna_score = row.get('Vanna_Dealer_Score', 0)
            output.append(f"   Vanna: {vanna:,.0f} | Dealer Score: {vanna_score:.1f}/4")
            output.append(f"      {self.interpret_vanna_mechanics(vanna)}")
            output.append("")
            
            # Charm Analysis
            charm_score = row.get('Charm_Dealer_Score', 0)
            output.append(f"   Charm: {charm:,.0f} | Dealer Score: {charm_score:.1f}/4 | DTE: {dte:.1f}")
            output.append(f"      {self.interpret_charm_mechanics(charm)}")
            output.append("")
            
            # OI and Volume
            output.append(f"   OI: {oi:,.0f} (Median: {median_oi:.0f}) | Volume: {volume:,.0f}")
            
            # Volume analysis (SEPARATE from score, for discretionary interpretation)
            if oi > 0 and volume > 0:
                vol_oi_ratio = volume / oi
                output.append(f"   Vol/OI: {vol_oi_ratio:.2f}x")
                output.append(f"      → {self.interpret_vol_oi(vol_oi_ratio, gex)}")
            elif oi > 0:
                output.append(f"   Vol/OI: 0.00x")
                output.append(f"      → NO VOLUME - Stale positioning")
            
            # Greek confluence check
            output.append("")
            greeks_aligned = []
            if gex > 0:  # Support level
                if vanna < 0:  # Negative vanna helps support (rising IV = dealers buy)
                    greeks_aligned.append("Vanna")
                if charm < 0:  # Negative charm helps support (dealers buy as expiry approaches)
                    greeks_aligned.append("Charm")
                greeks_aligned.insert(0, "GEX")
            else:  # Resistance level
                if vanna > 0:  # Positive vanna helps resistance (rising IV = dealers sell)
                    greeks_aligned.append("Vanna")
                if charm > 0:  # Positive charm helps resistance (dealers sell as expiry approaches)
                    greeks_aligned.append("Charm")
                greeks_aligned.insert(0, "GEX")
            
            confluence_count = len(greeks_aligned)
            output.append(f"   Greeks Aligned: {confluence_count}/3 ({', '.join(greeks_aligned) if greeks_aligned else 'None'})")
            
            # Trading guidance
            output.append("")
            if gex_score >= 3.5 and confluence_count >= 3:
                output.append(f"   ✅ STRONG SETUP - Consider full size (1.0%)")
            elif gex_score >= 2.5 and confluence_count >= 3:
                output.append(f"   ⚠️  MODERATE SETUP - Consider 75% size (0.75%)")
            elif gex_score >= 2.0 and confluence_count >= 2:
                output.append(f"   ⚠️  WEAK SETUP - Consider 50% size (0.5%) or SKIP")
            else:
                output.append(f"   ❌ SKIP - Insufficient confluence or dealer score")
            
            output.append("\n" + "-"*70)
        
        # Max Pain
        output.append("\n" + "="*70)
        output.append("MAX PAIN ANALYSIS")
        output.append("="*70)
        output.append(f"Max Pain: ${max_pain_strike:,.0f} | Current: ${current_price:,.0f}")
        
        if max_pain_strike > 0:
            distance_to_pain = ((max_pain_strike - current_price) / current_price) * 100
            output.append(f"Distance: {distance_to_pain:+.1f}%")
            
            if distance_to_pain > 0:
                output.append(f"UPWARD PULL toward Max Pain")
            else:
                output.append(f"DOWNWARD PULL toward Max Pain")
        
        output.append("\n" + "="*70)
        output.append("TRADING RULES (UPDATED)")
        output.append("="*70)
        output.append("\nDealer Score Thresholds (0-4 scale):")
        output.append("  3.5-4.0 = Strong structural level → Full size (1.0%)")
        output.append("  2.5-3.5 = Moderate level → 75% size (0.75%)")
        output.append("  2.0-2.5 = Weak level → 50% size (0.5%) or SKIP")
        output.append("  <2.0 = No structural support → SKIP")
        output.append("\nGreek Confluence Requirements:")
        output.append("  - Minimum 3/3 Greeks aligned for strong conviction")
        output.append("  - 2/3 Greeks = proceed with caution (smaller size)")
        output.append("  - Pay attention to WHICH Greeks conflict and why")
        output.append("\nVol/OI Discretionary Interpretation:")
        output.append("  - Support (positive GEX): Prefer LOW vol/OI (stable)")
        output.append("  - Resistance (negative GEX): Prefer HIGH vol/OI (fresh) or SKIP")
        output.append("  - Use as confirmation, not hard requirement")
        output.append("\nPrice Action Confirmation:")
        output.append("  - Wait for VWAP test or level touch")
        output.append("  - Look for rejection candles")
        output.append("  - Don't front-run the level")
        output.append("\nStop Loss Management:")
        output.append("  - Support levels: -0.5% to -0.6% (accounts for shakeouts)")
        output.append("  - If breaks >0.6%, that's real breakdown → exit")
        output.append("  - Track in journal: how far did it wick vs actual breakdown")
        
        output.append("\n" + "="*70)
        output.append("COMPLETE")
        output.append("="*70)
        
        # Print and save
        full_output = "\n".join(output)
        print(full_output)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"greeks_analysis_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(full_output)
        
        print(f"\n✓ Saved to {filename}")
        
        return analysis_df

if __name__ == "__main__":
    analyzer = RawGreeksAnalysis()
    df = analyzer.analyze_key_levels(days_out=30)
    
    if not df.empty:
        print("\n📊 Analysis complete - DataFrame available as 'df'")