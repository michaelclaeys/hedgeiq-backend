"""
HedgeIQ Backend API
FastAPI server for BTC options Greeks analytics
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from routers import greeks, levels
from cache.redis_client import init_cache, close_cache

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    await init_cache()
    print("🚀 HedgeIQ API starting...")
    yield
    # Shutdown
    await close_cache()
    print("👋 HedgeIQ API shutting down...")

app = FastAPI(
    title="HedgeIQ API",
    description="Real-time BTC Options Greeks Analytics",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - Allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (local HTML files work now)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(greeks.router, prefix="/api", tags=["Greeks"])
app.include_router(levels.router, prefix="/api", tags=["Levels"])

@app.get("/")
async def root():
    return {"status": "ok", "service": "HedgeIQ API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)