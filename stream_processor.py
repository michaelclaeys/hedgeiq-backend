"""
HedgeIQ Stream Processor
Integrated system that:
1. Connects to Deribit WebSocket for live trades
2. Updates dealer inventory in Redis
3. Recalculates GEX on every trade (or batched)
4. Stores results for API to serve

This runs as a separate worker process alongside your FastAPI app.
"""

import asyncio
import json
import websockets
from datetime import datetime, timedelta
from typing import Optional
import re
import os
import signal
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redis_state import RedisStateManager
from flow_based_gex import FlowBasedGEXCalculator
from deribit_websocket import parse_instrument_name


class HedgeIQStreamProcessor:
    """
    Main stream processor for HedgeIQ.
    Connects to Deribit, processes trades, calculates GEX.
    """
    
    DERIBIT_WS = "wss://www.deribit.com/ws/api/v2"
    DERIBIT_REST = "https://www.deribit.com/api/v2/public"
    
    def __init__(self, redis_url: Optional[str] = None, use_memory: bool = False):
        self.state = RedisStateManager(redis_url=redis_url, use_memory=use_memory)
        self.gex_calculator = FlowBasedGEXCalculator()
        self.ws = None
        self.running = False
        
        # Load Deribit API keys
        from dotenv import load_dotenv
        load_dotenv()
        self.client_id = os.getenv("DERIBIT_CLIENT_ID")
        self.client_secret = os.getenv("DERIBIT_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            print("⚠️  WARNING: Deribit API keys not found in .env")
            print("   DERIBIT_CLIENT_ID=your_client_id")
            print("   DERIBIT_CLIENT_SECRET=your_client_secret")
        
        # GEX recalculation settings
        self.trades_since_last_calc = 0
        self.calc_every_n_trades = 10  # Recalc GEX every N trades
        self.last_calc_time = None
        self.calc_interval_seconds = 5  # Or every 5 seconds, whichever first
        
        # Options data cache (refreshed periodically)
        self.options_data = None
        self.options_data_refreshed = None
        
        # Stats
        self.start_time = None
        self.total_trades = 0
    
    async def fetch_options_data(self):
        """Fetch current options chain from Deribit REST API"""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # Get all instruments
            async with session.get(
                f"{self.DERIBIT_REST}/get_instruments",
                params={"currency": "BTC", "kind": "option", "expired": "false"}
            ) as resp:
                data = await resp.json()
                instruments = data.get("result", [])
            
            # Get book summary for mark_iv
            async with session.get(
                f"{self.DERIBIT_REST}/get_book_summary_by_currency",
                params={"currency": "BTC", "kind": "option"}
            ) as resp:
                data = await resp.json()
                summaries = {s["instrument_name"]: s for s in data.get("result", [])}
            
            # Get spot price
            async with session.get(
                f"{self.DERIBIT_REST}/get_index_price",
                params={"index_name": "btc_usd"}
            ) as resp:
                data = await resp.json()
                spot_price = data.get("result", {}).get("index_price", 0)
                self.state.set_spot_price(spot_price)
        
        # Build options DataFrame
        import pandas as pd
        
        options_list = []
        target_date = datetime.now() + timedelta(days=30)  # 30 days out
        
        for inst in instruments:
            exp_ts = inst["expiration_timestamp"] / 1000
            exp_date = datetime.fromtimestamp(exp_ts)
            
            if exp_date > target_date:
                continue
            
            name = inst["instrument_name"]
            summary = summaries.get(name, {})
            
            options_list.append({
                "instrument": name,
                "strike": inst["strike"],
                "option_type": inst["option_type"],
                "expiration": exp_date,
                "mark_iv": summary.get("mark_iv", 50),
                "open_interest": summary.get("open_interest", 0)
            })
        
        self.options_data = pd.DataFrame(options_list)
        self.options_data_refreshed = datetime.now()
        
        print(f"✓ Fetched {len(self.options_data)} options, spot: ${spot_price:,.2f}")
        
        return spot_price
    
    async def connect_websocket(self):
        """Connect to Deribit WebSocket and authenticate"""
        print("Connecting to Deribit WebSocket...")
        self.ws = await websockets.connect(self.DERIBIT_WS)
        print("✓ Connected!")
        
        # Authenticate
        if self.client_id and self.client_secret:
            print("Authenticating...")
            auth_msg = {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "public/auth",
                "params": {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }
            }
            
            await self.ws.send(json.dumps(auth_msg))
            response = await self.ws.recv()
            auth_data = json.loads(response)
            
            if "result" in auth_data:
                print("✓ Authentication successful!")
            else:
                error = auth_data.get("error", {})
                raise Exception(f"Auth failed: {error.get('message')}")
        else:
            raise Exception("Missing Deribit API credentials")
        
        # Subscribe to trades
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/subscribe",
            "params": {
                "channels": ["trades.option.BTC.raw"]
            }
        }
        await self.ws.send(json.dumps(subscribe_msg))
        
        response = await self.ws.recv()
        data = json.loads(response)
        
        if "result" in data:
            print("✓ Subscribed to BTC options trades")
        else:
            print(f"⚠ Subscription response: {data}")
    
    async def process_trade(self, trade: dict):
        """Process a single trade and update state"""
        instrument = trade.get("instrument_name", "")
        parsed = parse_instrument_name(instrument)
        
        if not parsed:
            return
        
        strike = parsed["strike"]
        option_type = parsed["option_type"]
        amount = trade.get("amount", 0)
        direction = trade.get("direction", "")  # taker side
        
        # Update dealer inventory
        if direction == "buy":
            delta = -amount  # Taker bought, dealer sold = more short
        else:
            delta = amount   # Taker sold, dealer bought = more long
        
        new_pos = self.state.update_dealer_position(strike, option_type, delta)
        
        self.total_trades += 1
        self.trades_since_last_calc += 1
        
        # Log significant trades
        if amount >= 1.0:
            side = "🟢 BUY" if direction == "buy" else "🔴 SELL"
            type_str = "CALL" if option_type == "call" else "PUT"
            print(f"{side} {amount:.1f} {type_str}@{strike} → Dealer: {new_pos:+.1f}")
    
    async def recalculate_gex(self):
        """Recalculate GEX from current inventory"""
        if self.options_data is None or self.options_data.empty:
            return
        
        spot_price = self.state.get_spot_price() or 90000
        inventory = self.state.get_full_inventory()
        
        if not inventory:
            return
        
        # Calculate GEX
        result = self.gex_calculator.calculate_gex(
            dealer_inventory=inventory,
            options_data=self.options_data,
            btc_price=spot_price
        )
        
        # Store results
        gex_data = {
            "net_gex": result.net_gex,
            "flip_level": result.flip_level,
            "max_support": list(result.max_support),
            "max_resistance": list(result.max_resistance),
            "btc_price": result.btc_price,
            "timestamp": result.timestamp.isoformat(),
            "gex_by_strike": result.gex_by_strike.to_dict(orient="records") if not result.gex_by_strike.empty else []
        }
        
        self.state.store_gex_result(gex_data)
        self.last_calc_time = datetime.now()
        self.trades_since_last_calc = 0
        
        # Print summary
        regime = "POSITIVE γ" if result.net_gex > 0 else "NEGATIVE γ"
        flip_str = f"${result.flip_level:,.0f}" if result.flip_level else "N/A"
        print(f"📊 GEX Update: {regime} | Net: ${result.net_gex:,.0f} | Flip: {flip_str}")
    
    def should_recalculate(self) -> bool:
        """Check if we should recalculate GEX"""
        if self.last_calc_time is None:
            return True
        
        # Recalc if enough trades
        if self.trades_since_last_calc >= self.calc_every_n_trades:
            return True
        
        # Recalc if enough time passed
        if (datetime.now() - self.last_calc_time).seconds >= self.calc_interval_seconds:
            return True
        
        return False
    
    async def run(self):
        """Single connection run loop"""
        self.running = True
        self.start_time = datetime.now()
        
        print("\n" + "=" * 60)
        print("HEDGEIQ STREAM PROCESSOR")
        print("=" * 60)
        
        try:
            # Initial data fetch
            await self.fetch_options_data()
            
            # Connect WebSocket
            await self.connect_websocket()
            
            # Enable heartbeat
            heartbeat_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "public/set_heartbeat",
                "params": {"interval": 30}
            }
            await self.ws.send(json.dumps(heartbeat_msg))
            print("✓ Heartbeat enabled (30s interval)")
            
            print("\n🎯 Listening for trades...")
            print("=" * 60 + "\n")
            
            # Schedule periodic tasks
            last_options_refresh = datetime.now()
            
            while self.running:
                try:
                    # Wait for message with timeout (longer than heartbeat)
                    message = await asyncio.wait_for(self.ws.recv(), timeout=45.0)
                    data = json.loads(message)
                    
                    # Respond to heartbeat test requests
                    if data.get("method") == "heartbeat":
                        if data.get("params", {}).get("type") == "test_request":
                            pong = {
                                "jsonrpc": "2.0",
                                "id": 888,
                                "method": "public/test",
                                "params": {}
                            }
                            await self.ws.send(json.dumps(pong))
                        continue  # Don't process heartbeats as trades
                    
                    # Process trades
                    if "params" in data and "channel" in data["params"]:
                        channel = data["params"]["channel"]
                        
                        if channel.startswith("trades.option"):
                            trades = data["params"]["data"]
                            
                            for trade in trades:
                                await self.process_trade(trade)
                    
                    # Check if we should recalculate GEX
                    if self.should_recalculate():
                        await self.recalculate_gex()
                    
                    # Refresh options data periodically (every 5 minutes)
                    if (datetime.now() - last_options_refresh).seconds >= 300:
                        await self.fetch_options_data()
                        last_options_refresh = datetime.now()
                        
                except asyncio.TimeoutError:
                    # Send ping to test connection
                    print("... connection idle, sending ping ...")
                    ping = {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "public/test",
                        "params": {}
                    }
                    await self.ws.send(json.dumps(ping))
                    
                    # Still recalculate if needed
                    if self.should_recalculate():
                        await self.recalculate_gex()
                    continue
                    
        except websockets.exceptions.ConnectionClosed as e:
            print(f"⚠ WebSocket connection closed: {e}")
            raise  # Re-raise to trigger reconnect
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            raise  # Re-raise to trigger reconnect
        finally:
            self.running = False
            if self.ws:
                await self.ws.close()
            
            # Print session stats
            runtime = (datetime.now() - self.start_time).seconds if self.start_time else 0
            print(f"\n📈 Session Stats:")
            print(f"   Runtime: {runtime}s")
            print(f"   Trades processed: {self.total_trades}")
            print(f"   Trades/min: {self.total_trades / (runtime/60) if runtime > 0 else 0:.1f}")
    
    async def run_forever(self):
        """Main entry point with auto-reconnect"""
        print("Starting with auto-reconnect enabled...")
        
        while True:
            try:
                await self.run()
            except KeyboardInterrupt:
                print("\n⏹ Shutting down...")
                break
            except Exception as e:
                print(f"\n⚠️  Connection lost: {e}")
                print("   Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
                # Reset state for reconnection
                self.ws = None
                self.running = False
        
        # Print final inventory state
        print("\n" + "=" * 60)
        print("FINAL STATE")
        print("=" * 60)
        print(self.state.get_stats())
    
    def stop(self):
        """Stop the processor"""
        self.running = False


async def main():
    """Entry point with auto-reconnect"""
    # Parse environment
    redis_url = os.getenv("REDIS_URL")
    use_memory = os.getenv("USE_MEMORY_STATE", "false").lower() == "true"
    
    processor = HedgeIQStreamProcessor(
        redis_url=redis_url,
        use_memory=use_memory
    )
    
    # Handle shutdown gracefully
    def signal_handler(sig, frame):
        print("\n⏹ Shutting down...")
        processor.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await processor.run_forever()


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║                  HEDGEIQ STREAM PROCESSOR                 ║
║                                                           ║
║  Real-time flow-based GEX calculation for BTC options    ║
║                                                           ║
║  Environment Variables:                                   ║
║  - REDIS_URL: Redis connection string                     ║
║  - USE_MEMORY_STATE: "true" for in-memory (dev)          ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(main())
