"""
Greeks API Router
Endpoints for individual Greek calculations
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import sys
import os

# Add services to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))

from calculate_gex import GEXCalculator
from calculate_vanna import VannaCalculator
from calculate_charm import CharmCalculator
from calculate_max_pain import MaxPainCalculator
from deribit_data import DeribitDataFetcher

router = APIRouter()

# Initialize calculators (singleton pattern)
gex_calc = GEXCalculator()
vanna_calc = VannaCalculator()
charm_calc = CharmCalculator()
max_pain_calc = MaxPainCalculator()
data_fetcher = DeribitDataFetcher()

# Response models
class StrikeData(BaseModel):
    strike: float
    value: float
    open_interest: float
    volume: float

class GEXResponse(BaseModel):
    success: bool
    timestamp: datetime
    btc_price: float
    data: List[StrikeData]
    max_positive_gex: Optional[dict] = None
    max_negative_gex: Optional[dict] = None
    zero_gex_level: Optional[float] = None

class VannaResponse(BaseModel):
    success: bool
    timestamp: datetime
    btc_price: float
    data: List[StrikeData]
    max_positive_vanna: Optional[dict] = None
    max_negative_vanna: Optional[dict] = None

class CharmResponse(BaseModel):
    success: bool
    timestamp: datetime
    btc_price: float
    data: List[StrikeData]
    max_charm_strike: Optional[float] = None

class MaxPainResponse(BaseModel):
    success: bool
    timestamp: datetime
    btc_price: float
    max_pain_strike: float
    distance_percent: float
    pull_direction: str


@router.get("/gex", response_model=GEXResponse)
async def get_gex(
    days_out: int = Query(default=30, ge=1, le=90, description="Days to expiration")
):
    """
    Get Gamma Exposure (GEX) by strike
    
    Positive GEX = Support (dealers long gamma, will buy dips)
    Negative GEX = Resistance (dealers short gamma, will sell rips)
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        gex_df = gex_calc.calculate_gex(days_out=days_out)
        
        if gex_df.empty:
            raise HTTPException(status_code=503, detail="No GEX data available")
        
        # Convert to response format
        data = []
        for _, row in gex_df.iterrows():
            data.append(StrikeData(
                strike=row['strike'],
                value=row['gex'],
                open_interest=row['open_interest'],
                volume=row['volume']
            ))
        
        # Find key levels
        max_pos = gex_df.loc[gex_df['gex'].idxmax()]
        max_neg = gex_df.loc[gex_df['gex'].idxmin()]
        
        # Find zero GEX crossover
        relevant = gex_df[
            (gex_df['strike'] >= btc_price * 0.9) & 
            (gex_df['strike'] <= btc_price * 1.1)
        ].copy()
        
        zero_gex = None
        if not relevant.empty:
            relevant['gex_cumsum'] = relevant['gex'].cumsum()
            zero_idx = relevant['gex_cumsum'].abs().idxmin()
            zero_gex = float(relevant.loc[zero_idx, 'strike'])
        
        return GEXResponse(
            success=True,
            timestamp=datetime.utcnow(),
            btc_price=btc_price,
            data=data,
            max_positive_gex={"strike": float(max_pos['strike']), "value": float(max_pos['gex'])},
            max_negative_gex={"strike": float(max_neg['strike']), "value": float(max_neg['gex'])},
            zero_gex_level=zero_gex
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vanna", response_model=VannaResponse)
async def get_vanna(
    days_out: int = Query(default=30, ge=1, le=90)
):
    """
    Get Vanna Exposure by strike
    
    Positive Vanna: Rising IV = dealers sell spot, Falling IV = dealers buy
    Negative Vanna: Rising IV = dealers buy spot, Falling IV = dealers sell
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        vanna_df = vanna_calc.calculate_vanna(days_out=days_out)
        
        if vanna_df.empty:
            raise HTTPException(status_code=503, detail="No Vanna data available")
        
        data = []
        for _, row in vanna_df.iterrows():
            data.append(StrikeData(
                strike=row['strike'],
                value=row['vanna_exposure'],
                open_interest=row['open_interest'],
                volume=row['volume']
            ))
        
        max_pos = vanna_df.loc[vanna_df['vanna_exposure'].idxmax()]
        max_neg = vanna_df.loc[vanna_df['vanna_exposure'].idxmin()]
        
        return VannaResponse(
            success=True,
            timestamp=datetime.utcnow(),
            btc_price=btc_price,
            data=data,
            max_positive_vanna={"strike": float(max_pos['strike']), "value": float(max_pos['vanna_exposure'])},
            max_negative_vanna={"strike": float(max_neg['strike']), "value": float(max_neg['vanna_exposure'])}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/charm", response_model=CharmResponse)
async def get_charm(
    days_out: int = Query(default=30, ge=1, le=90)
):
    """
    Get Charm Exposure (Delta Decay) by strike
    
    Positive Charm: As expiry approaches, dealers sell spot
    Negative Charm: As expiry approaches, dealers buy spot
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        charm_df, max_charm_strike = charm_calc.calculate_charm(days_out=days_out)
        
        if charm_df.empty:
            raise HTTPException(status_code=503, detail="No Charm data available")
        
        data = []
        for _, row in charm_df.iterrows():
            data.append(StrikeData(
                strike=row['strike'],
                value=row['charm_exposure'],
                open_interest=row['open_interest'],
                volume=row['volume']
            ))
        
        return CharmResponse(
            success=True,
            timestamp=datetime.utcnow(),
            btc_price=btc_price,
            data=data,
            max_charm_strike=float(max_charm_strike)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/maxpain", response_model=MaxPainResponse)
async def get_max_pain(
    days_out: int = Query(default=30, ge=1, le=90)
):
    """
    Get Max Pain strike
    
    Max Pain = strike where option holders lose the most money
    Price tends to gravitate toward this level near expiry
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        pain_df, max_pain_strike = max_pain_calc.calculate_max_pain(days_out=days_out)
        
        if max_pain_strike == 0:
            raise HTTPException(status_code=503, detail="No Max Pain data available")
        
        distance_pct = ((max_pain_strike - btc_price) / btc_price) * 100
        pull_direction = "UP" if distance_pct > 0 else "DOWN"
        
        return MaxPainResponse(
            success=True,
            timestamp=datetime.utcnow(),
            btc_price=btc_price,
            max_pain_strike=float(max_pain_strike),
            distance_percent=distance_pct,
            pull_direction=pull_direction
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price")
async def get_btc_price():
    """Get current BTC price from Deribit"""
    try:
        price = data_fetcher.get_btc_price()
        return {
            "success": True,
            "timestamp": datetime.utcnow(),
            "btc_price": price
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/dashboard")
async def get_dashboard_data(
    days_out: int = Query(default=30, ge=1, le=90)
):
    """
    Get all Greeks data for dashboard in one call
    """
    try:
        btc_price = data_fetcher.get_btc_price()
        
        # Calculate all Greeks
        gex_df = gex_calc.calculate_gex(days_out=days_out)
        vanna_df = vanna_calc.calculate_vanna(days_out=days_out)
        charm_df, max_charm_strike = charm_calc.calculate_charm(days_out=days_out)
        pain_df, max_pain_strike = max_pain_calc.calculate_max_pain(days_out=days_out)
        
        # Calculate net values
        net_gex = float(gex_df['gex'].sum()) if not gex_df.empty else 0
        net_vanna = float(vanna_df['vanna_exposure'].sum()) if not vanna_df.empty else 0
        net_charm = float(charm_df['charm_exposure'].sum()) if not charm_df.empty else 0
        
        return {
            "success": True,
            "timestamp": datetime.utcnow(),
            "btc_price": btc_price,
            "net_gex": net_gex,
            "vanna": net_vanna,
            "charm": net_charm,
            "max_pain": float(max_pain_strike)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))