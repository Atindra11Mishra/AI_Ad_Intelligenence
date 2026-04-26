import json
import os
import re
import time
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

COPY_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


class AnalyzerServiceError(Exception):
    pass


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


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """
    Parses a JSON object from model output.
    Handles cases where the model accidentally wraps JSON in markdown fences.
    """
    if not text or not text.strip():
        raise AnalyzerServiceError("Empty response from Groq.")

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise AnalyzerServiceError(f"Failed to parse JSON from Groq response: {str(e)}") from e

    if not isinstance(parsed, dict):
        raise AnalyzerServiceError("Groq response JSON was not an object.")

    return parsed


def _with_retry(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """
    Runs a function once, then retries one more time on failure.
    """
    first_error: Exception | None = None

    for attempt in range(2):
        try:
            return fn()
        except Exception as e:
            first_error = e
            if attempt == 1:
                break

    raise AnalyzerServiceError(str(first_error))


def _groq_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not GROQ_API_KEY:
        raise AnalyzerServiceError("Missing GROQ_API_KEY in environment.")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

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

                raise AnalyzerServiceError(f"Groq request failed: {detail}") from e
            except httpx.HTTPError as e:
                raise AnalyzerServiceError(f"Groq request failed: {str(e)}") from e

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AnalyzerServiceError("Invalid response structure from Groq.") from e

    return _extract_json_from_text(content)


def analyze_copy(copy_text: str) -> dict:
    """
    Analyze ad copy and return:
    {
      "hook": str,
      "cta": str,
      "angle": "pain_point" | "aspiration" | "social_proof" | "offer" | "urgency"
    }
    """

    def _run() -> dict[str, Any]:
        safe_copy = copy_text.strip() if copy_text else ""

        payload = {
            "model": COPY_MODEL,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert direct-response advertising analyst. "
                        "Return only valid JSON. Do not include markdown, comments, or explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyze the following ad copy.\n\n"
                        "Extract JSON with exactly these keys:\n"
                        "{\n"
                        '  "hook": "opening line or main hook",\n'
                        '  "cta": "call to action if present, otherwise empty string",\n'
                        '  "angle": "one of: pain_point | aspiration | social_proof | offer | urgency"\n'
                        "}\n\n"
                        "Rules:\n"
                        "- angle must be exactly one of the allowed enum values.\n"
                        "- Return only valid JSON.\n"
                        "- No markdown.\n\n"
                        f"Ad copy:\n{safe_copy}"
                    ),
                },
            ],
        }

        parsed = _groq_request(payload)

        allowed_angles = {
            "pain_point",
            "aspiration",
            "social_proof",
            "offer",
            "urgency",
        }

        hook = parsed.get("hook")
        cta = parsed.get("cta")
        angle = parsed.get("angle")

        if not isinstance(hook, str):
            hook = ""
        if not isinstance(cta, str):
            cta = ""
        if angle not in allowed_angles:
            angle = "aspiration"

        return {
            "hook": hook,
            "cta": cta,
            "angle": angle,
        }

    return _with_retry(_run)


def analyze_image(image_url: str) -> dict:
    """
    Analyze ad image and return:
    {
      "visual_style": "minimal" | "bold" | "lifestyle" | "product_shot" | "before_after",
      "has_people": bool,
      "has_text_overlay": bool,
      "ugc_vs_produced": "ugc" | "produced",
      "product_visibility": "high" | "medium" | "low"
    }
    """

    def _run() -> dict[str, Any]:
        safe_image_url = image_url.strip() if image_url else ""
        if not safe_image_url:
            raise AnalyzerServiceError("Image URL is empty.")

        payload = {
            "model": VISION_MODEL,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert visual advertising analyst. "
                        "Return only valid JSON. Do not include markdown, comments, or explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this ad image.\n\n"
                                "Extract JSON with exactly these keys:\n"
                                "{\n"
                                '  "visual_style": "minimal | bold | lifestyle | product_shot | before_after",\n'
                                '  "has_people": true,\n'
                                '  "has_text_overlay": true,\n'
                                '  "ugc_vs_produced": "ugc | produced",\n'
                                '  "product_visibility": "high | medium | low"\n'
                                "}\n\n"
                                "Rules:\n"
                                "- visual_style must be exactly one of: minimal, bold, lifestyle, product_shot, before_after.\n"
                                "- has_people must be boolean.\n"
                                "- has_text_overlay must be boolean.\n"
                                "- ugc_vs_produced must be exactly one of: ugc, produced.\n"
                                "- product_visibility must be exactly one of: high, medium, low.\n"
                                "- Return only valid JSON.\n"
                                "- No markdown."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": safe_image_url,
                            },
                        },
                    ],
                },
            ],
        }

        parsed = _groq_request(payload)

        allowed_visual_styles = {
            "minimal",
            "bold",
            "lifestyle",
            "product_shot",
            "before_after",
        }
        allowed_ugc = {"ugc", "produced"}
        allowed_visibility = {"high", "medium", "low"}

        visual_style = parsed.get("visual_style")
        has_people = parsed.get("has_people")
        has_text_overlay = parsed.get("has_text_overlay")
        ugc_vs_produced = parsed.get("ugc_vs_produced")
        product_visibility = parsed.get("product_visibility")

        if visual_style not in allowed_visual_styles:
            visual_style = "product_shot"

        if not isinstance(has_people, bool):
            has_people = False

        if not isinstance(has_text_overlay, bool):
            has_text_overlay = False

        if ugc_vs_produced not in allowed_ugc:
            ugc_vs_produced = "produced"

        if product_visibility not in allowed_visibility:
            product_visibility = "medium"

        return {
            "visual_style": visual_style,
            "has_people": has_people,
            "has_text_overlay": has_text_overlay,
            "ugc_vs_produced": ugc_vs_produced,
            "product_visibility": product_visibility,
        }

    return _with_retry(_run)
