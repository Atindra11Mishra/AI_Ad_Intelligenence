import os
import time
from typing import Any
from urllib.parse import urlparse, urlencode

import httpx
from dotenv import load_dotenv

from services.text_quality import clean_ad_text

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_BASE_URL = "https://api.apify.com/v2"
ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/facebook-ads-library-scraper")
FACEBOOK_AD_COUNTRY = os.getenv("APIFY_FACEBOOK_AD_COUNTRY", "ALL")
FACEBOOK_AD_SORT_BY = os.getenv("APIFY_FACEBOOK_AD_SORT_BY", "most_recent")
MIN_CHARGED_RESULTS = 10
CONFIDENCE_THRESHOLD = 80


class ApifyServiceError(Exception):
    pass


def _safe_actor_id(actor_id: str) -> str:
    return actor_id.replace("/", "~")


def _build_ad_library_search_url(search_term: str) -> str:
    query = urlencode(
        {
            "active_status": "all",
            "ad_type": "all",
            "country": FACEBOOK_AD_COUNTRY,
            "q": search_term,
            "search_type": "keyword_unordered",
            "media_type": "image",
        }
    )
    return f"https://www.facebook.com/ads/library/?{query}"


def _build_ad_library_page_url(page_id: str) -> str:
    query = urlencode(
        {
            "active_status": "all",
            "ad_type": "all",
            "country": FACEBOOK_AD_COUNTRY,
            "media_type": "image",
            "view_all_page_id": page_id,
        }
    )
    return f"https://www.facebook.com/ads/library/?{query}"


def _format_http_error(error: httpx.HTTPError) -> str:
    if not isinstance(error, httpx.HTTPStatusError):
        return str(error)

    response = error.response
    response_text = response.text.strip()
    if len(response_text) > 1000:
        response_text = f"{response_text[:1000]}..."

    if response_text:
        return f"{error} Response body: {response_text}"

    return str(error)


def _to_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.replace(",", "").strip())
        except ValueError:
            return 0
    return 0


def _run_actor(actor_input: dict[str, Any]) -> list[dict[str, Any]]:
    if not APIFY_API_TOKEN:
        raise ApifyServiceError("Missing APIFY_API_TOKEN in environment.")

    headers = {
        "Authorization": f"Bearer {APIFY_API_TOKEN}",
        "Content-Type": "application/json",
    }
    actor_id = _safe_actor_id(ACTOR_ID)

    try:
        with httpx.Client(timeout=60.0) as client:
            run_response = client.post(
                f"{APIFY_BASE_URL}/acts/{actor_id}/runs",
                headers=headers,
                json=actor_input,
            )
            run_response.raise_for_status()
            run_data = run_response.json()
    except httpx.HTTPError as e:
        raise ApifyServiceError(f"Failed to start Apify actor run: {_format_http_error(e)}") from e

    run_id = run_data.get("data", {}).get("id")
    if not run_id:
        raise ApifyServiceError("Apify did not return a run ID.")

    dataset_id = None
    status = None

    try:
        with httpx.Client(timeout=60.0) as client:
            for _ in range(40):  # ~120 seconds max
                status_response = client.get(
                    f"{APIFY_BASE_URL}/actor-runs/{run_id}",
                    headers=headers,
                )
                status_response.raise_for_status()
                status_data = status_response.json().get("data", {})

                status = status_data.get("status")
                dataset_id = status_data.get("defaultDatasetId")

                if status == "SUCCEEDED":
                    break
                if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                    raise ApifyServiceError(f"Apify run ended with status: {status}")

                time.sleep(3)
            else:
                raise ApifyServiceError("Timed out while waiting for Apify actor run to finish.")
    except httpx.HTTPError as e:
        raise ApifyServiceError(f"Failed while polling Apify run status: {_format_http_error(e)}") from e

    if status != "SUCCEEDED":
        raise ApifyServiceError(f"Apify run did not succeed. Final status: {status}")

    if not dataset_id:
        raise ApifyServiceError("Apify run succeeded but no dataset ID was returned.")

    try:
        with httpx.Client(timeout=60.0) as client:
            items_response = client.get(
                f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
                headers=headers,
                params={"clean": "true"},
            )
            items_response.raise_for_status()
            items = items_response.json()
    except httpx.HTTPError as e:
        raise ApifyServiceError(f"Failed to fetch Apify dataset items: {_format_http_error(e)}") from e

    if not isinstance(items, list):
        raise ApifyServiceError("Unexpected dataset response from Apify.")

    if items and all(isinstance(item, dict) and "error" in item for item in items):
        errors = [str(item.get("error")) for item in items if isinstance(item, dict)]
        raise ApifyServiceError(f"Apify actor returned dataset errors: {'; '.join(errors)}")

    return [item for item in items if isinstance(item, dict)]


def _actor_input_for_url(url: str, count: int = MIN_CHARGED_RESULTS) -> dict[str, Any]:
    return {
        "urls": [{"url": url}],
        "count": max(count, MIN_CHARGED_RESULTS),
        "scrapePageAds.period": "",
        "scrapePageAds.activeStatus": "all",
        "scrapePageAds.sortBy": FACEBOOK_AD_SORT_BY,
        "scrapePageAds.countryCode": FACEBOOK_AD_COUNTRY,
    }


def _extract_copy_text(item: dict[str, Any]) -> str:
    bodies = item.get("bodies") or []

    if isinstance(bodies, list):
        parts: list[str] = []
        for body in bodies:
            if isinstance(body, str):
                text = clean_ad_text(body)
                if text:
                    parts.append(text)
            elif isinstance(body, dict):
                text = body.get("text") or body.get("body") or body.get("content")
                cleaned = clean_ad_text(text if isinstance(text, str) else None)
                if cleaned:
                    parts.append(cleaned)
        if parts:
            return " ".join(parts)

    for key in ("body", "copy", "adText", "text", "ad_text", "adText"):
        value = item.get(key)
        cleaned = clean_ad_text(value if isinstance(value, str) else None)
        if cleaned:
            return cleaned

    snapshot = item.get("snapshot")
    if isinstance(snapshot, dict):
        for key in ("body", "caption", "title", "link_description"):
            value = snapshot.get(key)
            cleaned = clean_ad_text(value if isinstance(value, str) else None)
            if cleaned:
                return cleaned
            if isinstance(value, dict):
                text = value.get("text")
                cleaned = clean_ad_text(text if isinstance(text, str) else None)
                if cleaned:
                    return cleaned

        cards = snapshot.get("cards") or []
        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict):
                    continue

                parts: list[str] = []
                seen_parts = set()
                for key in ("body", "title", "link_description"):
                    value = card.get(key)
                    cleaned = clean_ad_text(value if isinstance(value, str) else None)
                    if cleaned and cleaned not in seen_parts:
                        seen_parts.add(cleaned)
                        parts.append(cleaned)

                if parts:
                    return " ".join(parts)

    return ""


def _is_thumbnail_url(url: str) -> bool:
    normalized = url.lower()
    thumbnail_markers = ("s60x60", "s64x64", "p64x64", "s75x75", "p75x75")
    return any(marker in normalized for marker in thumbnail_markers)


def _canonical_image_url_key(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.split("?", 1)[0].strip().lower()

    path = parsed.path.rstrip("/").lower()
    if not path:
        return url.split("?", 1)[0].strip().lower()

    return path


def _card_has_video(card: dict[str, Any]) -> bool:
    video_keys = (
        "video_hd_url",
        "video_sd_url",
        "watermarked_video_hd_url",
        "watermarked_video_sd_url",
        "video_preview_image_url",
    )
    return any(bool(card.get(key)) for key in video_keys)


def _first_non_empty_url(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _creative_signature(copy_text: str, image_urls: list[str]) -> str:
    cleaned_copy = " ".join(clean_ad_text(copy_text).lower().split())
    image_keys = [_canonical_image_url_key(url) for url in image_urls if isinstance(url, str)]
    return "|".join([cleaned_copy, *sorted(set(image_keys))])


def _extract_image_urls(item: dict[str, Any]) -> list[str]:
    image_urls: list[str] = []

    snapshot_url = item.get("snapshot_url") or item.get("ad_snapshot_url") or item.get("adSnapshotUrl")
    if isinstance(snapshot_url, str) and snapshot_url.strip():
        image_urls.append(snapshot_url.strip())

    for key in ("media_url", "mediaUrl", "image_url", "imageUrl"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            image_urls.append(value.strip())

    image_candidates = item.get("images") or item.get("image_urls") or []
    if isinstance(image_candidates, list):
        for image in image_candidates:
            if isinstance(image, str) and image.strip():
                image_urls.append(image.strip())
            elif isinstance(image, dict):
                for key in ("url", "src", "imageUrl"):
                    value = image.get(key)
                    if isinstance(value, str) and value.strip():
                        image_urls.append(value.strip())
                        break

    snapshot = item.get("snapshot")
    if isinstance(snapshot, dict):
        cards = snapshot.get("cards") or []
        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, dict) or _card_has_video(card):
                    continue

                image_url = _first_non_empty_url(
                    card,
                    ("original_image_url", "image_url", "url", "resized_image_url"),
                )
                if image_url:
                    image_urls.append(image_url)

        snapshot_images = snapshot.get("images") or []
        if isinstance(snapshot_images, list):
            for image in snapshot_images:
                if isinstance(image, str) and image.strip():
                    image_urls.append(image.strip())
                elif isinstance(image, dict):
                    for key in ("url", "original_image_url", "resized_image_url"):
                        value = image.get(key)
                        if isinstance(value, str) and value.strip():
                            image_urls.append(value.strip())
                            break

    seen = set()
    deduped: list[str] = []
    for url in image_urls:
        canonical_key = _canonical_image_url_key(url)
        if canonical_key not in seen:
            seen.add(canonical_key)
            deduped.append(url)

    return sorted(deduped, key=_is_thumbnail_url)


def _extract_page_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = item.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    page_id = item.get("page_id") or snapshot.get("page_id")
    page_name = item.get("page_name") or snapshot.get("page_name")

    if not page_id or not page_name:
        return None

    return {
        "page_id": str(page_id),
        "name": str(page_name),
        "page_profile_uri": str(snapshot.get("page_profile_uri") or ""),
        "like_count": _to_int(
            snapshot.get("page_like_count")
            or item.get("like_count")
            or item.get("likes")
        ),
        "is_verified": bool(snapshot.get("is_verified") or item.get("is_verified") or False),
    }


def score_page(page: dict[str, Any], brand_name: str) -> int:
    score = 0

    if page.get("is_verified"):
        score += 100

    page_name = str(page.get("name") or "")
    if page_name.lower() == brand_name.lower():
        score += 50

    uri = str(page.get("page_profile_uri") or "")
    normalized_brand = brand_name.lower().replace(" ", "")
    normalized_uri = uri.lower().replace(" ", "")
    if normalized_brand and normalized_brand in normalized_uri:
        score += 30

    likes = _to_int(page.get("like_count"))
    if likes > 1_000_000:
        score += 40
    elif likes > 100_000:
        score += 20

    suspicious = ["fan", "official2", "page2", "backup", "fake"]
    if any(s in page_name.lower() for s in suspicious):
        score -= 50

    return score


def resolve_competitor_page(competitor_name: str) -> dict[str, Any]:
    items = _run_actor(_actor_input_for_url(_build_ad_library_search_url(competitor_name)))
    candidates_by_id: dict[str, dict[str, Any]] = {}

    for item in items:
        candidate = _extract_page_candidate(item)
        if not candidate:
            continue

        page_id = candidate["page_id"]
        existing = candidates_by_id.get(page_id)
        if not existing or candidate["like_count"] > existing["like_count"]:
            candidates_by_id[page_id] = candidate

    candidates = list(candidates_by_id.values())
    for candidate in candidates:
        candidate["score"] = score_page(candidate, competitor_name)

    sorted_candidates = sorted(
        candidates,
        key=lambda page: (int(page.get("score") or 0), int(page.get("like_count") or 0)),
        reverse=True,
    )

    if not sorted_candidates:
        return {
            "status": "needs_confirmation",
            "query": competitor_name,
            "candidates": [],
        }

    best_match = sorted_candidates[0]
    if int(best_match.get("score") or 0) < CONFIDENCE_THRESHOLD:
        return {
            "status": "needs_confirmation",
            "query": competitor_name,
            "candidates": sorted_candidates[:3],
        }

    return {
        "status": "resolved",
        "query": competitor_name,
        "page": best_match,
        "candidates": sorted_candidates[:3],
    }


def fetch_competitor_ads(competitor_name: str, page_id: str | None = None) -> list[dict]:
    url = (
        _build_ad_library_page_url(page_id)
        if page_id
        else _build_ad_library_search_url(competitor_name)
    )
    items = _run_actor(_actor_input_for_url(url))
    normalized_ads: list[dict] = []
    seen_creatives = set()

    for item in items:
        image_urls = _extract_image_urls(item)
        if not image_urls:
            continue
        copy_text = _extract_copy_text(item)
        creative_signature = _creative_signature(copy_text, image_urls)
        if creative_signature in seen_creatives:
            continue
        seen_creatives.add(creative_signature)

        ad_id = (
            item.get("ad_id")
            or item.get("adId")
            or item.get("id")
            or item.get("archive_id")
            or item.get("ad_archive_id")
        )
        snapshot = item.get("snapshot")
        snapshot_page_name = snapshot.get("page_name") if isinstance(snapshot, dict) else None
        page_name = (
            item.get("page_name")
            or item.get("pageName")
            or item.get("page_name_text")
            or snapshot_page_name
            or competitor_name
        )

        normalized_ads.append(
            {
                "ad_id": str(ad_id) if ad_id is not None else "",
                "page_name": str(page_name) if page_name is not None else competitor_name,
                "copy_text": copy_text,
                "image_urls": image_urls,
                "creative_signature": creative_signature,
            }
        )

    return normalized_ads
