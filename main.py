"""HedgeIQ Backend API - Production Ready"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from routers import greeks, levels
# Removed Redis for initial deployment simplicity

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    print("🚀 HedgeIQ API starting...")
    yield
    print("👋 HedgeIQ API shutting down...")

app = FastAPI(
    title="HedgeIQ API",
    description="Real-time BTC Options Greeks Analytics",
    version="1.0.0",
    lifespan=lifespan
)

# CORS - Allow all origins to ensure your Netlify frontend can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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