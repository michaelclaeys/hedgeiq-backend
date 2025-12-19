"""
Levels API Router
Combined analysis endpoint that returns key levels with all Greeks
This is the main endpoint your dashboard will use
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))

from calculate_gex import GEXCalculator
from calculate_vanna import VannaCalculator
from calculate_charm import CharmCalculator
from calculate_max_pain import MaxPainCalculator
from deribit_data import DeribitDataFetcher

router = APIRouter()

# Initialize
gex_calc = GEXCalculator()
vanna_calc = VannaCalculator()
charm_calc = CharmCalculator()
max_pain_calc = MaxPainCalculator()
data_fetcher = DeribitDataFetcher()


class KeyLevel(BaseModel):
    strike: float
    level_type: str  # "SUPPORT" or "RESISTANCE"
    distance_percent: float
    gex: float
    gex_dealer_score: float
    vanna: float
    vanna_dealer_score: float
    charm: float
    charm_dealer_score: float
    open_interest: float
    volume: float
    vol_oi_ratio: Optional[float] = None
    greeks_aligned: int
    aligned_greeks: List[str]
    is_round_number: bool
    round_type: Optional[str] = None  # "5K" or "1K"
    setup_quality: str  # "STRONG", "MODERATE", "WEAK", "SKIP"
    suggested_size: float  # 0, 0.5, 0.75, 1.0


class LevelsResponse(BaseModel):
    success: bool
    timestamp: datetime
    btc_price: float
    max_pain: float
    max_pain_distance_percent: float
    max_pain_pull: str
    net_gex: float
    net_vanna: float
    net_charm: float
    key_levels: List[KeyLevel]


def calculate_dealer_score(strike: float, open_interest: float, median_oi: float) -> float:
    """
    Dealer positioning score 0-4
    Higher = more reliable level
    """
    score = 0
    
    # Round numbers
    if strike % 5000 == 0:
        score += 1.5
    elif strike % 1000 == 0:
        score += 0.5
    
    # OI significance
    if open_interest > 2 * median_oi:
        score += 2
    elif open_interest > median_oi:
        score += 1
    
    return min(score, 4)


def get_setup_quality(dealer_score: float, greeks_aligned: int) -> tuple:
    """
    Returns (quality_label, suggested_size)
    """
    if dealer_score >= 3.5 and greeks_aligned >= 3:
        return ("STRONG", 1.0)
    elif dealer_score >= 2.5 and greeks_aligned >= 3:
        return ("MODERATE", 0.75)
    elif dealer_score >= 2.0 and greeks_aligned >= 2:
        return ("WEAK", 0.5)
    else:
        return ("SKIP", 0.0)


@router.get("/levels", response_model=LevelsResponse)
async def get_key_levels(
    days_out: int = Query(default=30, ge=1, le=90),
    top_n: int = Query(default=10, ge=5, le=20, description="Number of key levels to return")
):
    """
    Get key levels with full Greeks analysis
    
    This is your main dashboard endpoint. Returns:
    - Top N key levels by GEX magnitude
    - Each level includes GEX, Vanna, Charm, dealer scores
    - Greek confluence analysis
    - Setup quality rating
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        
        # Fetch all Greeks
        gex_df = gex_calc.calculate_gex(days_out=days_out)
        vanna_df = vanna_calc.calculate_vanna(days_out=days_out)
        charm_df, max_charm_strike = charm_calc.calculate_charm(days_out=days_out)
        pain_df, max_pain_strike = max_pain_calc.calculate_max_pain(days_out=days_out)
        
        if gex_df.empty:
            raise HTTPException(status_code=503, detail="No options data available")
        
        # Merge dataframes on strike
        merged = gex_df[['strike', 'gex', 'open_interest', 'volume']].copy()
        merged.columns = ['strike', 'gex', 'open_interest', 'volume']
        
        if not vanna_df.empty:
            vanna_merge = vanna_df[['strike', 'vanna_exposure']].copy()
            vanna_merge.columns = ['strike', 'vanna']
            merged = merged.merge(vanna_merge, on='strike', how='left')
        else:
            merged['vanna'] = 0
        
        if not charm_df.empty:
            charm_merge = charm_df[['strike', 'charm_exposure']].copy()
            charm_merge.columns = ['strike', 'charm']
            merged = merged.merge(charm_merge, on='strike', how='left')
        else:
            merged['charm'] = 0
        
        merged = merged.fillna(0)
        
        # Calculate median OI for dealer scores
        median_oi = merged['open_interest'].median()
        if median_oi == 0:
            median_oi = 1
        
        # Get top N by absolute GEX
        merged['abs_gex'] = merged['gex'].abs()
        top_levels = merged.nlargest(top_n, 'abs_gex').copy()
        
        # Build response
        key_levels = []
        
        for _, row in top_levels.iterrows():
            strike = row['strike']
            gex = row['gex']
            vanna = row['vanna']
            charm = row['charm']
            oi = row['open_interest']
            volume = row['volume']
            
            # Level type
            level_type = "SUPPORT" if gex > 0 else "RESISTANCE"
            
            # Distance from spot
            distance_pct = ((strike - btc_price) / btc_price) * 100
            
            # Dealer scores
            gex_score = calculate_dealer_score(strike, oi, median_oi)
            vanna_score = calculate_dealer_score(strike, oi, median_oi)
            charm_score = calculate_dealer_score(strike, oi, median_oi)
            
            # Vol/OI ratio
            vol_oi = volume / oi if oi > 0 else None
            
            # Round number check
            is_round = strike % 1000 == 0
            round_type = None
            if strike % 5000 == 0:
                round_type = "5K"
            elif strike % 1000 == 0:
                round_type = "1K"
            
            # Greek confluence
            aligned = ["GEX"]
            if gex > 0:  # Support
                if vanna < 0:
                    aligned.append("Vanna")
                if charm < 0:
                    aligned.append("Charm")
            else:  # Resistance
                if vanna > 0:
                    aligned.append("Vanna")
                if charm > 0:
                    aligned.append("Charm")
            
            greeks_aligned = len(aligned)
            
            # Setup quality
            quality, suggested_size = get_setup_quality(gex_score, greeks_aligned)
            
            key_levels.append(KeyLevel(
                strike=strike,
                level_type=level_type,
                distance_percent=distance_pct,
                gex=gex,
                gex_dealer_score=gex_score,
                vanna=vanna,
                vanna_dealer_score=vanna_score,
                charm=charm,
                charm_dealer_score=charm_score,
                open_interest=oi,
                volume=volume,
                vol_oi_ratio=vol_oi,
                greeks_aligned=greeks_aligned,
                aligned_greeks=aligned,
                is_round_number=is_round,
                round_type=round_type,
                setup_quality=quality,
                suggested_size=suggested_size
            ))
        
        # Sort by distance from current price
        key_levels.sort(key=lambda x: abs(x.distance_percent))
        
        # Calculate net exposures
        net_gex = merged['gex'].sum()
        net_vanna = merged['vanna'].sum()
        net_charm = merged['charm'].sum()
        
        # Max pain analysis
        max_pain_distance = ((max_pain_strike - btc_price) / btc_price) * 100 if max_pain_strike > 0 else 0
        max_pain_pull = "UP" if max_pain_distance > 0 else "DOWN"
        
        return LevelsResponse(
            success=True,
            timestamp=datetime.utcnow(),
            btc_price=btc_price,
            max_pain=float(max_pain_strike),
            max_pain_distance_percent=max_pain_distance,
            max_pain_pull=max_pain_pull,
            net_gex=net_gex,
            net_vanna=net_vanna,
            net_charm=net_charm,
            key_levels=key_levels
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_dashboard_metrics(
    days_out: int = Query(default=30, ge=1, le=90)
):
    """
    Quick metrics endpoint for dashboard cards
    Returns summary data without full level breakdown
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        
        gex_df = gex_calc.calculate_gex(days_out=days_out)
        vanna_df = vanna_calc.calculate_vanna(days_out=days_out)
        charm_df, max_charm_strike = charm_calc.calculate_charm(days_out=days_out)
        pain_df, max_pain_strike = max_pain_calc.calculate_max_pain(days_out=days_out)
        
        # Net exposures
        net_gex = gex_df['gex'].sum() if not gex_df.empty else 0
        net_vanna = vanna_df['vanna_exposure'].sum() if not vanna_df.empty else 0
        net_charm = charm_df['charm_exposure'].sum() if not charm_df.empty else 0
        
        # Key strike (highest absolute GEX)
        if not gex_df.empty:
            key_strike_row = gex_df.loc[gex_df['gex'].abs().idxmax()]
            key_strike = key_strike_row['strike']
            key_strike_gex = key_strike_row['gex']
        else:
            key_strike = 0
            key_strike_gex = 0
        
        # Determine market regime
        if net_gex > 0:
            regime = "POSITIVE_GAMMA"
            regime_description = "Dealers long gamma - expect mean reversion, support on dips"
        else:
            regime = "NEGATIVE_GAMMA"
            regime_description = "Dealers short gamma - expect trend continuation, volatile moves"
        
        return {
            "success": True,
            "timestamp": datetime.utcnow(),
            "btc_price": btc_price,
            "metrics": {
                "net_gex": net_gex,
                "net_gex_formatted": f"+${net_gex/1e9:.2f}B" if net_gex >= 0 else f"-${abs(net_gex)/1e9:.2f}B",
                "net_vanna": net_vanna,
                "net_charm": net_charm,
                "max_pain": max_pain_strike,
                "key_strike": key_strike,
                "key_strike_gex": key_strike_gex,
                "regime": regime,
                "regime_description": regime_description
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
