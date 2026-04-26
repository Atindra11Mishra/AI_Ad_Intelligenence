import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from services.apify import (
    _actor_input_for_url,
    _build_ad_library_page_url,
    _build_ad_library_search_url,
    _creative_signature,
    _extract_copy_text,
    _extract_image_urls,
    fetch_competitor_ads,
)
from services.text_quality import clean_ad_text, is_placeholder_text


class ApifyNormalizationTests(unittest.TestCase):
    def test_actor_input_fetches_most_recent_image_ads(self):
        actor_input = _actor_input_for_url("https://www.facebook.com/ads/library/?q=JBL")

        self.assertEqual(actor_input["scrapePageAds.sortBy"], "most_recent")
        self.assertEqual(actor_input["scrapePageAds.activeStatus"], "all")

        search_query = parse_qs(urlparse(_build_ad_library_search_url("JBL")).query)
        page_query = parse_qs(urlparse(_build_ad_library_page_url("123")).query)

        self.assertEqual(search_query["media_type"], ["image"])
        self.assertEqual(page_query["media_type"], ["image"])

    def test_placeholder_copy_is_treated_as_missing(self):
        self.assertTrue(is_placeholder_text("{{product.brand}}"))
        self.assertEqual(clean_ad_text("{{product.brand}}"), "")

        item = {
            "bodies": [{"text": "{{product.brand}}"}],
            "body": "{{product.brand}}",
            "snapshot": {
                "title": "Real benefit-led copy wins here",
            },
        }

        self.assertEqual(_extract_copy_text(item), "Real benefit-led copy wins here")

    def test_image_extraction_skips_video_and_profile_picture_assets(self):
        item = {
            "images": [
                {"url": "https://cdn.example.com/small.jpg?stp=dst-jpg_s60x60"},
                {"url": "https://cdn.example.com/large.jpg"},
            ],
            "snapshot": {
                "videos": [
                    {
                        "video_preview_image_url": "https://cdn.example.com/video-preview.jpg",
                        "video_hd_url": "https://cdn.example.com/video.mp4",
                    }
                ],
                "page_profile_picture_url": "https://cdn.example.com/profile.jpg",
            },
        }

        self.assertEqual(
            _extract_image_urls(item),
            [
                "https://cdn.example.com/large.jpg",
                "https://cdn.example.com/small.jpg?stp=dst-jpg_s60x60",
            ],
        )

    def test_card_copy_and_images_are_extracted_from_snapshot_cards(self):
        item = {
            "snapshot": {
                "cards": [
                    {
                        "body": "The new LinkBuds let you clip in and stay aware.",
                        "title": "Clip. Play. Stay aware.",
                        "link_description": "Sony wireless earbuds",
                        "original_image_url": "https://cdn.example.com/sony-large.jpg",
                        "resized_image_url": "https://cdn.example.com/sony-small.jpg?stp=dst-jpg_s600x600",
                    }
                ]
            }
        }

        self.assertEqual(
            _extract_copy_text(item),
            "The new LinkBuds let you clip in and stay aware. Clip. Play. Stay aware. Sony wireless earbuds",
        )
        self.assertEqual(
            _extract_image_urls(item),
            [
                "https://cdn.example.com/sony-large.jpg",
            ],
        )

    def test_image_dedupe_uses_canonical_url_without_query_params(self):
        item = {
            "images": [
                {"url": "https://cdn.example.com/path/product.jpg?oh=abc"},
                {"url": "https://cdn.example.com/path/product.jpg?oh=def"},
            ]
        }

        self.assertEqual(
            _extract_image_urls(item),
            ["https://cdn.example.com/path/product.jpg?oh=abc"],
        )

    def test_video_cards_are_skipped_even_when_they_have_preview_images(self):
        item = {
            "snapshot": {
                "cards": [
                    {
                        "body": "Video creative should not become an image ad.",
                        "original_image_url": "https://cdn.example.com/video-still.jpg",
                        "video_hd_url": "https://cdn.example.com/video.mp4",
                    }
                ]
            }
        }

        self.assertEqual(_extract_image_urls(item), [])

    def test_creative_signature_ignores_ad_id_and_image_query_params(self):
        first = _creative_signature(
            "Big bass, compact speaker. Shop now.",
            ["https://cdn.example.com/ad.jpg?oh=abc"],
        )
        second = _creative_signature(
            " Big bass, compact speaker.  Shop now. ",
            ["https://cdn.example.com/ad.jpg?oh=def"],
        )

        self.assertEqual(first, second)

    def test_fetch_competitor_ads_dedupes_same_creative_with_different_ad_ids(self):
        items = [
            {
                "ad_id": "meta-1",
                "body": "Big bass, compact speaker. Shop now.",
                "images": [{"url": "https://cdn.example.com/ad.jpg?oh=abc"}],
            },
            {
                "ad_id": "meta-2",
                "body": "Big bass, compact speaker. Shop now.",
                "images": [{"url": "https://cdn.example.com/ad.jpg?oh=def"}],
            },
        ]

        with patch("services.apify._run_actor", return_value=items):
            ads = fetch_competitor_ads("JBL", page_id="123")

        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0]["ad_id"], "meta-1")


if __name__ == "__main__":
    unittest.main()
