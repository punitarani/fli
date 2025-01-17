"""Main FastAPI application module."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logging import setup_logging
from .middleware import RequestTracingMiddleware
from .routers import dates, flights

# Setup logging
setup_logging()

# Create FastAPI app
app = FastAPI(
    title="Flight Search API",
    description="API for searching flights and finding the best dates to fly",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request tracing middleware
app.add_middleware(RequestTracingMiddleware)

# Include routers
app.include_router(
    flights.router,
    prefix="/flights",
    tags=["flights"],
)
app.include_router(
    dates.router,
    prefix="/dates",
    tags=["dates"],
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
