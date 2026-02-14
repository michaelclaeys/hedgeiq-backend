# HedgeIQ Backend

Backend API for HedgeIQ, a real-time options greeks analytics platform for cryptocurrency derivatives.

## Overview

HedgeIQ provides live options greeks analysis and gamma exposure (GEX) tracking for crypto markets. The backend connects to Deribit's WebSocket API to stream real-time options flow data, computes dealer positioning and greeks exposure, and serves analytics through a FastAPI REST API.

## Key Features

- Real-time options flow tracking via Deribit WebSocket
- Gamma exposure (GEX) computation from live trade data
- Dealer positioning and inventory tracking
- Strike-level greeks aggregation
- REST API for frontend consumption
- Redis-backed state management for production deployments

## Tech Stack

- Python / FastAPI
- Deribit WebSocket API
- Redis (production) / in-memory state (development)
- NumPy for greeks calculations

## Getting Started

1. Install dependencies: `pip install -r requirements.txt`
2. Configure environment variables for Deribit API access
3. Run the server: `uvicorn main:app --reload`

## License

MIT
