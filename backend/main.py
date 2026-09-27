from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from backend.app.core.config import settings
from backend.app.core.database import db_manager
from backend.app.api.routes import router as api_router

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("discovery_engine")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize SQLite tables and WAL mode
    logger.info("Initializing SQLite database tables...")
    db_manager.init_db()
    logger.info(f"Database initialized at: {settings.DB_PATH}")
    yield
    # Shutdown
    logger.info("Discovery Engine backend shutting down.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-Powered Discovery Engine analyzing cognitive retrieval struggles in Google Photos.",
    lifespan=lifespan
)

# Enable CORS for frontend dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router, prefix="/api/v1")

from fastapi import Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

# Mount dashboard static files
app.mount("/dashboard", StaticFiles(directory=str(settings.FRONTEND_DIR), html=True), name="dashboard")

@app.get("/")
def root(request: Request):
    """
    Root endpoint:
    - If accessed via web browser (Accept: text/html), redirects to /dashboard/
    - Otherwise returns API meta information
    """
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        return RedirectResponse(url="/dashboard/")
    return {
        "engine": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "api": "/api/v1/health",
        "dashboard": "/dashboard/"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
