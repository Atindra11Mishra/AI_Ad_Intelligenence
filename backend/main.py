import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.database import Base, engine
from routers.brand import router as brand_router
from routers.chat import router as chat_router
from routers.competitors import router as competitors_router

app = FastAPI(
    title="Competitive Ad Intelligence API",
    version="1.0.0",
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://ai-ad-intelligenence.vercel.app",
]


def get_cors_origins() -> list[str]:
    raw_origins = os.getenv("CORS_ORIGINS")
    if not raw_origins:
        return DEFAULT_CORS_ORIGINS

    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or DEFAULT_CORS_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()


def ensure_schema_compatibility():
    inspector = inspect(engine)
    if "ads" not in inspector.get_table_names():
        return

    ad_columns = {column["name"] for column in inspector.get_columns("ads")}
    if "analysis_error" not in ad_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE ads ADD COLUMN analysis_error TEXT"))


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(brand_router)
app.include_router(competitors_router)
app.include_router(chat_router)
