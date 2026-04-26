import json
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ad, Brand, Competitor
from services.text_quality import clean_ad_text

load_dotenv()

router = APIRouter(tags=["chat"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
CHAT_MODEL = "llama-3.3-70b-versatile"


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    brand_id: int
    message: str = Field(..., min_length=1)
    history: list[ChatHistoryMessage] = []


def _json_loads_safe(value: str | None, default: Any = None) -> Any:
    if not value:
        return default

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def build_context(brand_id: int, db: Session) -> str:
    brand = db.query(Brand).filter(Brand.id == brand_id).first()

    if not brand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id={brand_id} not found.",
        )

    profile = _json_loads_safe(brand.value_props, default=[])
    value_props_text = ", ".join(str(item) for item in profile) if isinstance(profile, list) else str(profile)

    context = (
        "BRAND PROFILE:\n"
        f"Name: {brand.name}\n"
        f"Category: {brand.category or ''}\n"
        f"Tone: {brand.tone or ''}\n"
        f"Audience: {brand.target_audience or ''}\n"
        f"Value Props: {value_props_text}\n\n"
        "COMPETITOR INTELLIGENCE:\n"
    )


    competitors = (
        db.query(Competitor)
        .filter(Competitor.brand_id == brand_id)
        .order_by(Competitor.created_at.asc())
        .all()
    )

    for competitor in competitors:
        ads = (
            db.query(Ad)
            .filter(Ad.competitor_id == competitor.id)
            .order_by(Ad.fetched_at.desc())
            .all()
        )

        context += f"[{competitor.name} - {len(ads)} ads]\n"

        for ad in ads:
            cleaned_copy_text = clean_ad_text(ad.copy_text)
            has_copy = bool(cleaned_copy_text)
            copy_text = cleaned_copy_text or "Unavailable from scraper"
            hook = ad.copy_hook if has_copy else ""
            cta = ad.copy_cta if has_copy else ""
            angle = ad.copy_angle if has_copy else ""
            creative_category = ad.creative_category if has_copy else ""
            summary = (
                ad.analysis_summary
                if has_copy
                else "Copy unavailable from scraper; use only structured visual fields for this ad."
            )

            context += (
                f"- Ad ID: {ad.ad_id_meta or ad.id} | "
                f"Format: {ad.format or ''} | "
                f"Hook: {hook or ''} | "
                f"CTA: {cta or ''} | "
                f"Angle: {angle or ''} | "
                f"Visual: {ad.visual_style or ''} | "
                f"People: {ad.has_people} | "
                f"Text Overlay: {ad.has_text_overlay} | "
                f"UGC: {ad.ugc_vs_produced or ''} | "
                f"Product Visibility: {ad.product_visibility or ''} | "
                f"Creative Category: {creative_category or ''}\n"
                f"  Copy: {copy_text}\n"
                f"  Summary: {summary or ''}\n"
            )

    return context


async def _groq_stream(messages: list[dict[str, str]]):
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing GROQ_API_KEY in environment.",
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": CHAT_MODEL,
        "temperature": 0.4,
        "stream": True,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                GROQ_CHAT_URL,
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if not line.startswith("data: "):
                        continue

                    data = line.removeprefix("data: ").strip()

                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )

                        if delta:
                            yield delta

                    except json.JSONDecodeError:
                        continue

    except httpx.HTTPError as e:
        yield f"\n\n[Groq streaming error: {str(e)}]"


def build_chat_messages(payload: ChatRequest, db: Session) -> list[dict[str, str]]:
    context = build_context(payload.brand_id, db)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a creative ad strategist. "
                "Answer ONLY from the brand profile and competitor ad data provided below. "
                "Do not use outside knowledge, assumptions, or generic category advice. "
                "When making a claim about a competitor, cite the competitor name and ad ID from the context. "
                "If the data does not support an answer, say what is missing instead of guessing. "
                "Treat ads marked as copy unavailable as visual-only evidence. "
                "Be specific and grounded.\n\n"
                f"{context}"
            ),
        }
    ]

    for item in payload.history:
        messages.append(
            {
                "role": item.role,
                "content": item.content,
            }
        )

    messages.append(
        {
            "role": "user",
            "content": payload.message,
        }
    )

    return messages


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    messages = build_chat_messages(payload, db)

    return StreamingResponse(
        _groq_stream(messages),
        media_type="text/plain",
    )
