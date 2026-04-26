import json
import os
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Brand

load_dotenv()

router = APIRouter(prefix="", tags=["brands"])

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1/scrape"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class BrandSetupRequest(BaseModel):
    name: str
    website_url: HttpUrl


class BrandResponse(BaseModel):
    id: int
    name: str
    website_url: str
    category: str | None
    positioning: str | None
    tone: str | None
    target_audience: str | None
    value_props: str | None   # JSON array as TEXT
    visual_style: str | None
    created_at: Any

    class Config:
        from_attributes = True


def scrape_website_markdown(website_url: str) -> str:
    if not FIRECRAWL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing FIRECRAWL_API_KEY in environment.",
        )

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": website_url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(FIRECRAWL_BASE_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Firecrawl request failed: {str(e)}",
        )

    markdown = (
        data.get("data", {}).get("markdown")
        or data.get("markdown")
        or ""
    ).strip()

    if not markdown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firecrawl returned no markdown content.",
        )

    return markdown


def extract_brand_profile(markdown: str) -> Dict[str, Any]:
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing GROQ_API_KEY in environment.",
        )

    prompt = (
        "Extract a brand profile as JSON with keys: category, positioning, "
        "tone, target_audience (string), value_props (array), visual_style. "
        "Return only valid JSON, no markdown."
    )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You extract structured brand information from website content.",
            },
            {
                "role": "user",
                "content": f"{prompt}\n\nWebsite markdown:\n{markdown[:8000]}",
            },
        ],
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(GROQ_CHAT_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq request failed: {str(e)}",
        )

    try:
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response structure from Groq.",
        )

    # Groq sometimes wraps JSON in markdown fences (```json ... ```) — strip them
    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()

    try:
        profile = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq did not return valid JSON.",
        )

    required_keys = {
        "category",
        "positioning",
        "tone",
        "target_audience",
        "value_props",
        "visual_style",
    }

    missing = required_keys - set(profile.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq JSON missing keys: {sorted(list(missing))}",
        )

    if not isinstance(profile.get("value_props"), list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Groq returned invalid value_props; expected an array.",
        )

    return profile


@router.post("/brand/setup", response_model=BrandResponse)
def setup_brand(payload: BrandSetupRequest, db: Session = Depends(get_db)):
    markdown = scrape_website_markdown(str(payload.website_url))
    profile = extract_brand_profile(markdown)

    brand = Brand(
        name=payload.name,
        website_url=str(payload.website_url),
        category=profile.get("category"),
        positioning=profile.get("positioning"),
        tone=profile.get("tone"),
        target_audience=profile.get("target_audience"),
        value_props=json.dumps(profile.get("value_props", [])),
        visual_style=profile.get("visual_style"),
    )

    db.add(brand)
    db.commit()
    db.refresh(brand)

    return brand


@router.get("/brands", response_model=List[BrandResponse])
def get_brands(db: Session = Depends(get_db)):
    brands = db.query(Brand).order_by(Brand.created_at.desc()).all()
    return brands