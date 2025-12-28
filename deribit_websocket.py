"""
Deribit WebSocket Trade Listener
Phase 1: Flow-Based Dealer Inventory Tracking

This connects to Deribit's WebSocket API and tracks every BTC options trade.
For each trade, we look at the taker_side to determine dealer positioning:
  - taker_side = "buy"  → Retail/fund bought → Dealer SOLD (SHORT)
  - taker_side = "sell" → Retail/fund sold  → Dealer BOUGHT (LONG)

We maintain a running inventory of dealer positions per strike/type.

REQUIRES: Deribit API keys in .env file:
  DERIBIT_CLIENT_ID=your_client_id
  DERIBIT_CLIENT_SECRET=your_client_secret
"""

import asyncio
import json
import websockets
import os
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Optional
import re

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


@dataclass
class DealerInventory:
    """Tracks dealer positions across all strikes"""
    # Structure: {strike: {"call": position, "put": position}}
    # Positive = dealer is LONG, Negative = dealer is SHORT
    positions: Dict[int, Dict[str, float]] = field(default_factory=lambda: defaultdict(lambda: {"call": 0.0, "put": 0.0}))
    trade_count: int = 0
    last_updated: Optional[datetime] = None
    
    def update_from_trade(self, strike: int, option_type: str, amount: float, taker_side: str):
        """
        Update dealer inventory based on a trade.
        
        taker_side = "buy" → Taker bought FROM dealer → Dealer SOLD → Dealer goes MORE SHORT
        taker_side = "sell" → Taker sold TO dealer → Dealer BOUGHT → Dealer goes MORE LONG
        """
        if taker_side == "buy":
            # Taker bought, dealer sold → dealer position decreases (more short)
            delta = -amount
        else:
            # Taker sold, dealer bought → dealer position increases (more long)
            delta = +amount
        
        self.positions[strike][option_type] += delta
        self.trade_count += 1
        self.last_updated = datetime.now()
        
        return delta
    
    def get_position(self, strike: int, option_type: str) -> float:
        """Get dealer's current position at a strike"""
        return self.positions[strike][option_type]
    
    def get_all_positions(self) -> Dict[int, Dict[str, float]]:
        """Get all positions, sorted by strike"""
        return dict(sorted(self.positions.items()))
    
    def summary(self) -> str:
        """Print a summary of significant positions"""
        lines = [
            f"\n{'='*60}",
            f"DEALER INVENTORY SUMMARY",
            f"Trades processed: {self.trade_count}",
            f"Last update: {self.last_updated}",
            f"{'='*60}",
            f"\n{'Strike':<10} {'Call Pos':<15} {'Put Pos':<15}"
        ]
        
        # Only show strikes with non-zero positions
        for strike in sorted(self.positions.keys()):
            call_pos = self.positions[strike]["call"]
            put_pos = self.positions[strike]["put"]
            
            if abs(call_pos) > 0.01 or abs(put_pos) > 0.01:
                call_str = f"{call_pos:+.2f}" if call_pos != 0 else "-"
                put_str = f"{put_pos:+.2f}" if put_pos != 0 else "-"
                lines.append(f"${strike:<9,} {call_str:<15} {put_str:<15}")
        
        return "\n".join(lines)


def parse_instrument_name(instrument_name: str) -> Optional[dict]:
    """
    Parse Deribit instrument name into components.
    Example: BTC-27DEC24-85000-P → {underlying: BTC, expiry: 27DEC24, strike: 85000, type: put}
    """
    # Pattern: BTC-DDMMMYY-STRIKE-C/P
    pattern = r'^(BTC)-(\d{1,2}[A-Z]{3}\d{2})-(\d+)-([CP])$'
    match = re.match(pattern, instrument_name)
    
    if not match:
        return None
    
    return {
        "underlying": match.group(1),
        "expiry": match.group(2),
        "strike": int(match.group(3)),
        "option_type": "call" if match.group(4) == "C" else "put"
    }


class DeribitTradeListener:
    """
    WebSocket listener for Deribit BTC options trades.
    Tracks dealer inventory in real-time based on taker flow.
    """
    
    WS_URL = "wss://www.deribit.com/ws/api/v2"
    
    def __init__(self):
        self.inventory = DealerInventory()
        self.ws = None
        self.running = False
        
        # Load API keys from environment
        self.client_id = os.getenv("DERIBIT_CLIENT_ID")
        self.client_secret = os.getenv("DERIBIT_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            print("⚠️  WARNING: DERIBIT_CLIENT_ID or DERIBIT_CLIENT_SECRET not found in .env")
            print("   Create a .env file with your Deribit API keys:")
            print("   DERIBIT_CLIENT_ID=your_client_id")
            print("   DERIBIT_CLIENT_SECRET=your_client_secret")
        
    async def connect(self):
        """Establish WebSocket connection and authenticate"""
        print(f"Connecting to Deribit WebSocket...")
        self.ws = await websockets.connect(self.WS_URL)
        print(f"✓ Connected!")
        
        # Authenticate with API keys
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
                print(f"❌ Authentication failed: {error.get('message', 'Unknown error')}")
                print(f"   Error code: {error.get('code')}")
                raise Exception("Deribit authentication failed")
        else:
            print("❌ No API keys - cannot access raw trade data")
            raise Exception("Missing Deribit API credentials")
        
        return self.ws
    
    async def subscribe_to_trades(self):
        """Subscribe to all BTC option trades"""
        # Subscribe to trades for ALL BTC options
        # Channel format: trades.option.{currency}.{interval}
        # Using "raw" for every single trade
        
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "public/subscribe",
            "params": {
                "channels": ["trades.option.BTC.raw"]
            }
        }
        
        await self.ws.send(json.dumps(subscribe_msg))
        print(f"Subscribing to BTC options trades...")
        
        # Wait for subscription confirmation
        response = await self.ws.recv()
        data = json.loads(response)
        
        if "result" in data:
            print(f"✓ Subscription confirmed!")
        else:
            error = data.get("error", {})
            print(f"❌ Subscription failed: {error}")
            raise Exception(f"Subscription failed: {error}")
    
    async def process_trade(self, trade: dict):
        """Process a single trade and update inventory"""
        instrument = trade.get("instrument_name", "")
        
        # Parse instrument name
        parsed = parse_instrument_name(instrument)
        if not parsed:
            return  # Skip non-standard instruments
        
        strike = parsed["strike"]
        option_type = parsed["option_type"]
        amount = trade.get("amount", 0)
        direction = trade.get("direction", "")  # "buy" or "sell" - this is taker side
        price = trade.get("price", 0)
        iv = trade.get("iv", 0)
        
        # Update inventory
        delta = self.inventory.update_from_trade(strike, option_type, amount, direction)
        
        # Get current position at this strike
        current_pos = self.inventory.get_position(strike, option_type)
        
        # Print trade info
        side_emoji = "🟢" if direction == "buy" else "🔴"
        type_emoji = "📈" if option_type == "call" else "📉"
        
        print(f"{side_emoji} {type_emoji} {instrument:<25} | "
              f"Size: {amount:>8.2f} | "
              f"Price: {price:.4f} | "
              f"IV: {iv:.1f}% | "
              f"Dealer Δ: {delta:+.2f} | "
              f"Dealer Pos: {current_pos:+.2f}")
    
    async def listen(self):
        """Main listening loop with heartbeat"""
        self.running = True
        last_summary = datetime.now()
        
        # Enable heartbeat - Deribit will ping us every 30 seconds
        heartbeat_msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "public/set_heartbeat",
            "params": {"interval": 30}
        }
        await self.ws.send(json.dumps(heartbeat_msg))
        print("✓ Heartbeat enabled (30s interval)")
        
        print("\n" + "="*80)
        print("LISTENING FOR TRADES...")
        print("🟢 = Retail BOUGHT (dealer sold) | 🔴 = Retail SOLD (dealer bought)")
        print("📈 = Call | 📉 = Put")
        print("="*80 + "\n")
        
        try:
            while self.running:
                try:
                    # Increased timeout to 45s (heartbeat is 30s)
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
                    
                    # Check if it's a trade notification
                    if "params" in data and "channel" in data["params"]:
                        channel = data["params"]["channel"]
                        
                        if channel.startswith("trades.option"):
                            trades = data["params"]["data"]
                            
                            for trade in trades:
                                await self.process_trade(trade)
                    
                    # Print summary every 60 seconds
                    if (datetime.now() - last_summary).seconds >= 60:
                        print(self.inventory.summary())
                        last_summary = datetime.now()
                        
                except asyncio.TimeoutError:
                    # Send a ping to test connection
                    print("... connection idle, sending ping ...")
                    ping = {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "public/test",
                        "params": {}
                    }
                    await self.ws.send(json.dumps(ping))
                    continue
                    
        except websockets.exceptions.ConnectionClosed as e:
            print(f"WebSocket connection closed: {e}")
            raise  # Re-raise to trigger reconnect
        except Exception as e:
            print(f"Error: {e}")
            raise  # Re-raise to trigger reconnect
        finally:
            self.running = False
    
    async def run(self):
        """Single connection attempt"""
        try:
            await self.connect()
            await self.subscribe_to_trades()
            await self.listen()
        finally:
            if self.ws:
                await self.ws.close()
    
    async def run_forever(self):
        """Main entry point with auto-reconnect"""
        print("Starting with auto-reconnect enabled...")
        
        while True:
            try:
                await self.run()
            except KeyboardInterrupt:
                print("\nShutting down...")
                break
            except Exception as e:
                print(f"\n⚠️  Connection lost: {e}")
                print("   Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
                # Reset state for reconnection
                self.ws = None
                self.running = False
        
        # Print final summary on exit
        print(self.inventory.summary())


async def main():
    """Run the trade listener with auto-reconnect"""
    listener = DeribitTradeListener()
    await listener.run_forever()


if __name__ == "__main__":
    print("="*60)
    print("DERIBIT FLOW-BASED TRADE LISTENER")
    print("Phase 1: Proof of Concept")
    print("="*60)
    print("\nThis script connects to Deribit WebSocket and tracks")
    print("dealer inventory based on taker_side of each trade.")
    print("\nPress Ctrl+C to stop and see summary.\n")
    
    asyncio.run(main())