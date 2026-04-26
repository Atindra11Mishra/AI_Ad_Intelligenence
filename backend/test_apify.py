"""
Quick test script to see raw Apify output.
Run from backend/ with: python test_apify.py
"""
import json
import os
import time
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_BASE_URL = "https://api.apify.com/v2"
ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/facebook-ads-library-scraper")
FACEBOOK_AD_COUNTRY = os.getenv("APIFY_FACEBOOK_AD_COUNTRY", "ALL")

SEARCH_TERM = "Sony"  # Change this to test different competitors
MAX_RESULTS = 3       # Requested result count; actor enforces a minimum below
MIN_CHARGED_RESULTS = 10


def safe_actor_id(actor_id: str) -> str:
    return actor_id.replace("/", "~")


def build_ad_library_search_url(search_term: str) -> str:
    query = urlencode(
        {
            "active_status": "all",
            "ad_type": "all",
            "country": FACEBOOK_AD_COUNTRY,
            "q": search_term,
            "search_type": "keyword_unordered",
            "media_type": "all",
        }
    )
    return f"https://www.facebook.com/ads/library/?{query}"


def raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        print(f"HTTP {response.status_code} response body:")
        print(response.text)
        raise


def main():
    if not APIFY_API_TOKEN:
        print("❌ APIFY_API_TOKEN not set in .env")
        return

    headers = {
        "Authorization": f"Bearer {APIFY_API_TOKEN}",
        "Content-Type": "application/json",
    }
    actor_id = safe_actor_id(ACTOR_ID)
    actor_count = max(MAX_RESULTS, MIN_CHARGED_RESULTS)
    actor_input = {
        "urls": [{"url": build_ad_library_search_url(SEARCH_TERM)}],
        "count": actor_count,
        "scrapePageAds.period": "",
        "scrapePageAds.activeStatus": "all",
        "scrapePageAds.sortBy": "impressions_desc",
        "scrapePageAds.countryCode": FACEBOOK_AD_COUNTRY,
    }

    # Step 1: Start the actor run
    print(f"🚀 Starting Apify actor for: '{SEARCH_TERM}'...")
    if actor_count != MAX_RESULTS:
        print(
            f"Requested {MAX_RESULTS} results, but this actor requires at least "
            f"{MIN_CHARGED_RESULTS}; using count={actor_count}."
        )
    print("Actor input:")
    print(json.dumps(actor_input, indent=2))
    with httpx.Client(timeout=60.0) as client:
        run_response = client.post(
            f"{APIFY_BASE_URL}/acts/{actor_id}/runs",
            headers=headers,
            json=actor_input,
        )
        raise_for_status(run_response)
        run_data = run_response.json()

    run_id = run_data.get("data", {}).get("id")
    print(f"✅ Run started — ID: {run_id}")

    # Step 2: Poll until done
    print("⏳ Waiting for actor to finish...")
    dataset_id = None
    status = None

    with httpx.Client(timeout=60.0) as client:
        for attempt in range(40):
            status_response = client.get(
                f"{APIFY_BASE_URL}/actor-runs/{run_id}",
                headers=headers,
            )
            raise_for_status(status_response)
            status_data = status_response.json().get("data", {})

            status = status_data.get("status")
            dataset_id = status_data.get("defaultDatasetId")
            print(f"   [{attempt + 1}] status: {status}")

            if status == "SUCCEEDED":
                break
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                print(f"❌ Actor failed with status: {status}")
                return

            time.sleep(3)

    if status != "SUCCEEDED":
        print("❌ Timed out waiting for actor.")
        return

    print(f"✅ Actor succeeded. Dataset ID: {dataset_id}")

    # Step 3: Fetch raw items
    print("\n📦 Fetching dataset items...")
    with httpx.Client(timeout=60.0) as client:
        items_response = client.get(
            f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
            headers=headers,
            params={"clean": "true"},
        )
        raise_for_status(items_response)
        items = items_response.json()

    print(f"✅ Got {len(items)} items\n")

    # Step 4: Print raw output
    if not items:
        print("⚠️  No items returned by the actor.")
        return

    if all(isinstance(item, dict) and "error" in item for item in items):
        print("Actor returned dataset errors:")
        for item in items:
            print(f"- {item.get('error')}")
        return

    print("=" * 60)
    print(f"FIRST ITEM — All keys: {list(items[0].keys())}")
    print("=" * 60)
    print(json.dumps(items[0], indent=2, ensure_ascii=False))
    print("=" * 60)

    if len(items) > 1:
        print(f"\nSECOND ITEM — All keys: {list(items[1].keys())}")
        print("=" * 60)
        print(json.dumps(items[1], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
