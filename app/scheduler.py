from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging

from app.cache import UserTier, set_cache, data_cache

# Set up logging so we can see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the scheduler
scheduler = BackgroundScheduler()

def fetch_and_cache_tier_data(tier: str):
    """
    This function runs on a schedule.
    It fetches data and stores it in the cache.
    
    Args:
        tier: Either "pro" or "starter"
    """
    try:
        logger.info(f"🔄 Fetching data for {tier} tier...")
        
        # Import the wrapper we created
        from app.greeks_wrapper import fetch_and_calculate_all_data
        
        if tier == "pro":
            # PRO TIER: Always fetch fresh data from Deribit
            logger.info("   Calling Deribit API and calculating Greeks...")
            cached_data = fetch_and_calculate_all_data(days_out=30)
            
            # Store in Pro's cache
            set_cache(UserTier.PRO, cached_data)
            logger.info(f"✅ PRO cache updated at {datetime.utcnow()}")
            logger.info(f"   - BTC: ${cached_data['btc_price']:,.2f}")
            logger.info(f"   - Signals: {len(cached_data['signals'])}")
        
        elif tier == "starter":
            # STARTER TIER: Reuse Pro's data (efficient!)
            if data_cache["pro"]["data"]:
                # Pro has data, just copy it
                logger.info("   Copying Pro's cached data...")
                set_cache(UserTier.STARTER, data_cache["pro"]["data"])
                logger.info(f"✅ STARTER cache updated from Pro at {datetime.utcnow()}")
            else:
                # Pro cache is empty (shouldn't happen), fetch fresh
                logger.warning("⚠️  Pro cache empty! Fetching fresh for Starter...")
                cached_data = fetch_and_calculate_all_data(days_out=30)
                set_cache(UserTier.STARTER, cached_data)
                logger.info(f"✅ STARTER cache updated with fresh data at {datetime.utcnow()}")
                
    except Exception as e:
        # If something goes wrong, log the error
        logger.error(f"❌ Failed to update {tier} cache: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

def start_scheduler():
    """
    Initialize and start the background scheduler.
    This is called when the server starts up.
    """
    logger.info("="*50)
    logger.info("🚀 STARTING HEDGEIQ SCHEDULER")
    logger.info("="*50)
    
    # IMMEDIATE FETCH: Populate caches right now (don't wait for timer)
    logger.info("\n📦 Populating initial caches...")
    fetch_and_cache_tier_data("pro")
    fetch_and_cache_tier_data("starter")
    
    # SCHEDULE PRO: Run every 1 minute
    scheduler.add_job(
        lambda: fetch_and_cache_tier_data("pro"),
        'interval',
        minutes=1,
        id='pro_refresh',
        replace_existing=True
    )
    logger.info("\n⏰ Pro refresh scheduled: Every 1 minute")
    
    # SCHEDULE STARTER: Run every 15 minutes
    scheduler.add_job(
        lambda: fetch_and_cache_tier_data("starter"),
        'interval',
        minutes=15,
        id='starter_refresh',
        replace_existing=True
    )
    logger.info("⏰ Starter refresh scheduled: Every 15 minutes")
    
    # Start the scheduler (it now runs in background)
    scheduler.start()
    logger.info("\n✅ Scheduler running in background")
    logger.info("="*50)

def stop_scheduler():
    """
    Stop the scheduler when server shuts down.
    """
    scheduler.shutdown()
    logger.info("🛑 Scheduler stopped")