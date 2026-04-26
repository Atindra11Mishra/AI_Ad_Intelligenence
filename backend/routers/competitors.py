import asyncio
import json
import os
import re
import time
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ad, Brand, Competitor
from services.analyzer import AnalyzerServiceError, analyze_copy, analyze_image
from services.apify import (
    ApifyServiceError,
    _creative_signature,
    fetch_competitor_ads,
    resolve_competitor_page,
)
from services.text_quality import clean_ad_text

load_dotenv()

router = APIRouter(prefix="", tags=["competitors"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
SUMMARY_MODEL = "llama-3.3-70b-versatile"
COPY_TO_IMAGE_DELAY_SECONDS = 2.5
IMAGE_TO_SUMMARY_DELAY_SECONDS = 3.5
AD_ANALYSIS_DELAY_SECONDS = 2.5


class CompetitorFetchRequest(BaseModel):
    brand_id: int
    competitor_names: list[str] = Field(default_factory=list)
    competitors: list["ResolvedCompetitorRequest"] = Field(default_factory=list)


class ResolvedCompetitorRequest(BaseModel):
    name: str
    page_id: str | None = None
    page_name: str | None = None


class CompetitorResolveRequest(BaseModel):
    competitor_names: list[str] = Field(..., min_length=1)


def _ensure_brand_exists(db: Session, brand_id: int) -> Brand:
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id={brand_id} not found.",
        )
    return brand


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads_safe(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _retry_delay_from_response(response: httpx.Response) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass

    try:
        message = response.json().get("error", {}).get("message", "")
    except (json.JSONDecodeError, AttributeError):
        message = response.text

    match = re.search(r"try again in ([0-9.]+)\s*(ms|s)", message, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        return max(value / 1000 if match.group(2).lower() == "ms" else value, 1.0)

    return 5.0


def _select_analysis_image_url(image_urls: list[str]) -> str:
    thumbnail_markers = (
        "s60x60",
        "s64x64",
        "p64x64",
        "s75x75",
        "p75x75",
    )

    for image_url in image_urls:
        if not isinstance(image_url, str):
            continue

        normalized = image_url.lower()
        if not any(marker in normalized for marker in thumbnail_markers):
            return image_url

    return image_urls[0]


def _generate_analysis_summary(fields: dict[str, Any]) -> str:
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Missing GROQ_API_KEY in environment.",
        )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = (
        "Ad data JSON:\n"
        f"{json.dumps(fields, ensure_ascii=False)}\n\n"
        "Write exactly 2 short sentences. "
        "Sentence 1 should state the concrete product, offer, visual approach, or copy angle used. "
        "Sentence 2 should explain the likely buyer motivation or strategic purpose, grounded only in the fields above. "
        "Avoid generic openings like 'This ad' or 'The creative strategy'. "
        "Do not add facts that are not present in the ad data."
    )

    payload = {
        "model": SUMMARY_MODEL,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write concise competitor ad observations from scraped ad fields. "
                    "Use specific evidence and avoid boilerplate."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            for attempt in range(5):
                try:
                    response = client.post(GROQ_CHAT_URL, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < 4:
                        time.sleep(_retry_delay_from_response(e.response))
                        continue

                    response_text = e.response.text.strip()
                    if len(response_text) > 1000:
                        response_text = f"{response_text[:1000]}..."

                    detail = str(e)
                    if response_text:
                        detail = f"{detail} Response body: {response_text}"

                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Groq summary request failed: {detail}",
                    )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Groq summary request failed: {str(e)}",
        )

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid summary response structure from Groq.",
        )


@router.post("/competitors/fetch")
def fetch_competitors_ads(
    payload: CompetitorFetchRequest,
    db: Session = Depends(get_db),
):
    _ensure_brand_exists(db, payload.brand_id)

    requested_competitors: list[ResolvedCompetitorRequest] = []

    for raw_name in payload.competitor_names:
        competitor_name = raw_name.strip()
        if competitor_name:
            requested_competitors.append(ResolvedCompetitorRequest(name=competitor_name))

    for competitor in payload.competitors:
        competitor_name = competitor.name.strip()
        if competitor_name:
            requested_competitors.append(
                ResolvedCompetitorRequest(
                    name=competitor_name,
                    page_id=competitor.page_id.strip() if competitor.page_id else None,
                    page_name=competitor.page_name.strip() if competitor.page_name else None,
                )
            )

    if not requested_competitors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one competitor name.",
        )

    competitors_added = 0
    total_ads_fetched = 0
    duplicate_ads_skipped = 0
    errors: list[dict[str, str]] = []

    for requested_competitor in requested_competitors:
        competitor_name = requested_competitor.name.strip()
        stored_competitor_name = requested_competitor.page_name or competitor_name

        existing_competitors = (
            db.query(Competitor)
            .filter(Competitor.brand_id == payload.brand_id)
            .all()
        )
        competitor = next(
            (
                item
                for item in existing_competitors
                if item.name.strip().lower() == stored_competitor_name.strip().lower()
            ),
            None,
        )

        if competitor is None:
            competitor = Competitor(
                brand_id=payload.brand_id,
                name=stored_competitor_name,
            )
            db.add(competitor)
            db.commit()
            db.refresh(competitor)
            competitors_added += 1

        try:
            ads = fetch_competitor_ads(competitor_name, page_id=requested_competitor.page_id)
        except ApifyServiceError as e:
            errors.append(
                {
                    "competitor": competitor_name,
                    "error": str(e),
                }
            )
            continue

        existing_ad_ids = {
            str(ad_id)
            for (ad_id,) in db.query(Ad.ad_id_meta)
            .filter(Ad.competitor_id == competitor.id)
            .filter(Ad.ad_id_meta.is_not(None))
            .all()
            if ad_id
        }
        existing_creative_signatures = {
            _creative_signature(ad.copy_text or "", _json_loads_safe(ad.image_urls, default=[]))
            for ad in db.query(Ad)
            .filter(Ad.competitor_id == competitor.id)
            .all()
        }

        for raw_ad in ads:
            image_urls = raw_ad.get("image_urls") or []

            if not image_urls:
                continue

            raw_ad_id = raw_ad.get("ad_id")
            normalized_ad_id = str(raw_ad_id) if raw_ad_id else ""
            if normalized_ad_id and normalized_ad_id in existing_ad_ids:
                duplicate_ads_skipped += 1
                continue

            copy_text = raw_ad.get("copy_text") or ""
            creative_signature = (
                raw_ad.get("creative_signature")
                if isinstance(raw_ad.get("creative_signature"), str)
                else _creative_signature(copy_text, image_urls)
            )
            if creative_signature in existing_creative_signatures:
                duplicate_ads_skipped += 1
                continue

            ad = Ad(
                competitor_id=competitor.id,
                ad_id_meta=normalized_ad_id,
                format="image" if len(image_urls) == 1 else "carousel",
                image_urls=_json_dumps(image_urls),
                copy_text=copy_text,
            )

            db.add(ad)
            if normalized_ad_id:
                existing_ad_ids.add(normalized_ad_id)
            existing_creative_signatures.add(creative_signature)
            total_ads_fetched += 1

        db.commit()

    return {
        "status": "success" if not errors else "partial_success",
        "competitors_added": competitors_added,
        "total_ads_fetched": total_ads_fetched,
        "duplicate_ads_skipped": duplicate_ads_skipped,
        "errors": errors,
    }


@router.post("/competitors/resolve-pages")
def resolve_competitor_pages(payload: CompetitorResolveRequest):
    results = []
    errors: list[dict[str, str]] = []

    for raw_name in payload.competitor_names:
        competitor_name = raw_name.strip()
        if not competitor_name:
            continue

        try:
            results.append(resolve_competitor_page(competitor_name))
        except ApifyServiceError as e:
            errors.append(
                {
                    "competitor": competitor_name,
                    "error": str(e),
                }
            )

    return {
        "status": "success" if not errors else "partial_success",
        "results": results,
        "errors": errors,
    }


@router.post("/competitors/analyze/{brand_id}")
async def analyze_competitor_ads(
    brand_id: int,
    db: Session = Depends(get_db),
):
    _ensure_brand_exists(db, brand_id)

    ads = (
        db.query(Ad)
        .join(Competitor, Ad.competitor_id == Competitor.id)
        .filter(Competitor.brand_id == brand_id)
        .filter(Ad.analysis_summary.is_(None))
        .all()
    )

    ads_analyzed = 0
    errors: list[dict[str, str]] = []

    for ad in ads:
        image_urls = _json_loads_safe(ad.image_urls, default=[])

        if not image_urls:
            ad.analysis_error = "Skipped because ad has no image URLs."
            db.add(ad)
            db.commit()
            errors.append(
                {
                    "ad_id": str(ad.id),
                    "error": "Skipped because ad has no image URLs.",
                }
            )
            continue

        first_image_url = _select_analysis_image_url(image_urls)

        try:
            cleaned_copy_text = clean_ad_text(ad.copy_text)
            if cleaned_copy_text:
                copy_result = await asyncio.to_thread(analyze_copy, cleaned_copy_text)
                await asyncio.sleep(COPY_TO_IMAGE_DELAY_SECONDS)
            else:
                copy_result = {
                    "hook": "",
                    "cta": "",
                    "angle": "",
                }

            image_result = await asyncio.to_thread(analyze_image, first_image_url)
            await asyncio.sleep(IMAGE_TO_SUMMARY_DELAY_SECONDS)

            combined_fields = {
                "copy_text": cleaned_copy_text,
                "copy_hook": copy_result.get("hook", ""),
                "copy_cta": copy_result.get("cta", ""),
                "copy_angle": copy_result.get("angle", ""),
                "visual_style": image_result.get("visual_style", ""),
                "has_people": image_result.get("has_people", False),
                "has_text_overlay": image_result.get("has_text_overlay", False),
                "ugc_vs_produced": image_result.get("ugc_vs_produced", ""),
                "product_visibility": image_result.get("product_visibility", ""),
                "format": ad.format,
                "image_urls": image_urls,
            }

            summary = await asyncio.to_thread(
                _generate_analysis_summary,
                combined_fields,
            )

            ad.copy_hook = combined_fields["copy_hook"]
            ad.copy_cta = combined_fields["copy_cta"]
            ad.copy_angle = combined_fields["copy_angle"]
            ad.visual_style = combined_fields["visual_style"]
            ad.has_people = combined_fields["has_people"]
            ad.has_text_overlay = combined_fields["has_text_overlay"]
            ad.ugc_vs_produced = combined_fields["ugc_vs_produced"]
            ad.product_visibility = combined_fields["product_visibility"]

            ad.creative_category = (
                f"{combined_fields['visual_style']}_{combined_fields['copy_angle']}"
                if combined_fields["copy_angle"]
                else combined_fields["visual_style"]
            )

            ad.analysis_summary = summary
            ad.analysis_error = None

            db.add(ad)
            db.commit()
            db.refresh(ad)

            ads_analyzed += 1
            await asyncio.sleep(AD_ANALYSIS_DELAY_SECONDS)

        except (AnalyzerServiceError, HTTPException) as e:
            db.rollback()

            if isinstance(e, HTTPException):
                error_detail = str(e.detail)
            else:
                error_detail = str(e)

            ad.analysis_error = error_detail
            db.add(ad)
            db.commit()

            errors.append(
                {
                    "ad_id": str(ad.id),
                    "error": error_detail,
                }
            )

        except Exception as e:
            db.rollback()
            error_detail = str(e)
            ad.analysis_error = error_detail
            db.add(ad)
            db.commit()
            errors.append(
                {
                    "ad_id": str(ad.id),
                    "error": error_detail,
                }
            )

    return {
        "status": "success" if not errors else "partial_success",
        "ads_analyzed": ads_analyzed,
        "errors": errors,
    }


@router.get("/competitors/ads/{brand_id}")
def get_competitors_with_ads(
    brand_id: int,
    db: Session = Depends(get_db),
):
    _ensure_brand_exists(db, brand_id)

    competitors = (
        db.query(Competitor)
        .filter(Competitor.brand_id == brand_id)
        .order_by(Competitor.created_at.desc())
        .all()
    )

    result = []

    for competitor in competitors:
        ads_payload = []

        for ad in competitor.ads:
            cleaned_copy_text = clean_ad_text(ad.copy_text)
            has_copy = bool(cleaned_copy_text)
            analysis_summary = (
                ad.analysis_summary
                if has_copy
                else "Copy unavailable from scraper; visual analysis shown only."
            )

            ads_payload.append(
                {
                    "id": ad.id,
                    "ad_id_meta": ad.ad_id_meta,
                    "format": ad.format,
                    "image_urls": _json_loads_safe(ad.image_urls, default=[]),
                    "copy_text": cleaned_copy_text,
                    "copy_hook": ad.copy_hook if has_copy else "",
                    "copy_cta": ad.copy_cta if has_copy else "",
                    "copy_angle": ad.copy_angle if has_copy else "",
                    "visual_style": ad.visual_style,
                    "has_people": ad.has_people,
                    "has_text_overlay": ad.has_text_overlay,
                    "ugc_vs_produced": ad.ugc_vs_produced,
                    "product_visibility": ad.product_visibility,
                    "creative_category": ad.creative_category if has_copy else ad.visual_style,
                    "analysis_summary": analysis_summary,
                    "analysis_error": ad.analysis_error,
                    "fetched_at": ad.fetched_at,
                }
            )

        result.append(
            {
                "id": competitor.id,
                "name": competitor.name,
                "brand_id": competitor.brand_id,
                "created_at": competitor.created_at,
                "ads": ads_payload,
            }
        )

    return result
