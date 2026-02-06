from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
from contextlib import asynccontextmanager

from app.scheduler import start_scheduler

# Lifecycle events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize data, scheduler etc.
    print("Startup: Initializing Application...")
    start_scheduler()
    yield
    # Shutdown
    print("Shutdown: Cleaning up...")


app = FastAPI(title="Short Selling Backtester API", lifespan=lifespan)

from app.routers import data

app.include_router(data.router, prefix="/api", tags=["Data"])

# CORS Configuration
origins = [
    "http://localhost:3000",  # Next.js frontend
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def read_health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
