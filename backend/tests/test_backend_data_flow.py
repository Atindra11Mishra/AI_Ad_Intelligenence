import asyncio
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Ad, Brand, Competitor
from routers.chat import ChatRequest, build_chat_messages, build_context
from routers.competitors import CompetitorFetchRequest, analyze_competitor_ads, fetch_competitors_ads


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def seed_brand_with_ads(db):
    brand = Brand(
        name="Boat",
        website_url="https://example.com",
        category="Audio electronics",
        positioning="Affordable stylish audio accessories",
        tone="Young and energetic",
        target_audience="Young adults who want stylish wireless audio",
        value_props=json.dumps(["Affordable", "Stylish", "Long battery life"]),
        visual_style="bold lifestyle product imagery",
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)

    competitor = Competitor(brand_id=brand.id, name="JBL")
    db.add(competitor)
    db.commit()
    db.refresh(competitor)

    ad = Ad(
        competitor_id=competitor.id,
        ad_id_meta="meta-123",
        format="image",
        image_urls=json.dumps(
            [
                "https://cdn.example.com/jbl-small-s60x60.jpg",
                "https://cdn.example.com/jbl-large.jpg",
            ]
        ),
        copy_text="Feel every beat with JBL BassBoost. Shop now and save 20%.",
    )
    db.add(ad)
    db.commit()
    db.refresh(ad)

    return brand, competitor, ad


class BackendDataFlowTests(unittest.TestCase):
    def test_chat_context_contains_real_competitor_ad_evidence(self):
        db = make_session()
        try:
            brand, _, _ = seed_brand_with_ads(db)

            context = build_context(brand.id, db)

            self.assertIn("BRAND PROFILE", context)
            self.assertIn("JBL", context)
            self.assertIn("meta-123", context)
            self.assertIn("Feel every beat with JBL BassBoost", context)
        finally:
            db.close()

    def test_chat_system_prompt_requires_grounded_ad_id_citations(self):
        db = make_session()
        try:
            brand, _, _ = seed_brand_with_ads(db)
            request = ChatRequest(
                brand_id=brand.id,
                message="What hooks are competitors using?",
                history=[],
            )

            messages = build_chat_messages(request, db)
            system_prompt = messages[0]["content"]
            self.assertIn("Answer ONLY from the brand profile", system_prompt)
            self.assertIn("Do not use outside knowledge", system_prompt)
            self.assertIn("cite the competitor name and ad ID", system_prompt)
            self.assertIn("If the data does not support an answer", system_prompt)
            self.assertIn("meta-123", system_prompt)
            self.assertIn("Feel every beat with JBL BassBoost", system_prompt)
            self.assertEqual(messages[-1]["content"], "What hooks are competitors using?")
        finally:
            db.close()

    def test_analysis_flow_passes_known_copy_and_image_to_model_functions(self):
        db = make_session()
        try:
            brand, _, ad = seed_brand_with_ads(db)
            seen = {"copy": None, "image": None, "summary_fields": None}

            def fake_analyze_copy(copy_text):
                seen["copy"] = copy_text
                return {
                    "hook": "Feel every beat with JBL BassBoost.",
                    "cta": "Shop now",
                    "angle": "offer",
                }

            def fake_analyze_image(image_url):
                seen["image"] = image_url
                return {
                    "visual_style": "product_shot",
                    "has_people": False,
                    "has_text_overlay": True,
                    "ugc_vs_produced": "produced",
                    "product_visibility": "high",
                }

            def fake_summary(fields):
                seen["summary_fields"] = fields
                return "JBL leads with a product-focused offer using bold bass positioning."

            with patch("routers.competitors.analyze_copy", fake_analyze_copy), patch(
                "routers.competitors.analyze_image", fake_analyze_image
            ), patch("routers.competitors._generate_analysis_summary", fake_summary), patch(
                "routers.competitors.COPY_TO_IMAGE_DELAY_SECONDS", 0
            ), patch("routers.competitors.IMAGE_TO_SUMMARY_DELAY_SECONDS", 0), patch(
                "routers.competitors.AD_ANALYSIS_DELAY_SECONDS", 0
            ):
                result = asyncio.run(analyze_competitor_ads(brand.id, db=db))

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["ads_analyzed"], 1)
            self.assertEqual(
                seen["copy"],
                "Feel every beat with JBL BassBoost. Shop now and save 20%.",
            )
            self.assertEqual(seen["image"], "https://cdn.example.com/jbl-large.jpg")
            self.assertEqual(seen["summary_fields"]["copy_angle"], "offer")

            db.refresh(ad)
            self.assertEqual(ad.copy_hook, "Feel every beat with JBL BassBoost.")
            self.assertEqual(ad.copy_cta, "Shop now")
            self.assertEqual(ad.copy_angle, "offer")
            self.assertEqual(ad.visual_style, "product_shot")
            self.assertEqual(ad.creative_category, "product_shot_offer")
            self.assertIn("product-focused offer", ad.analysis_summary)
        finally:
            db.close()

    def test_analysis_failure_is_persisted_on_ad(self):
        db = make_session()
        try:
            brand, _, ad = seed_brand_with_ads(db)

            def fail_analyze_copy(_copy_text):
                raise RuntimeError("copy model unavailable")

            with patch("routers.competitors.analyze_copy", fail_analyze_copy):
                result = asyncio.run(analyze_competitor_ads(brand.id, db=db))

            self.assertEqual(result["status"], "partial_success")
            self.assertEqual(result["ads_analyzed"], 0)
            self.assertEqual(result["errors"][0]["ad_id"], str(ad.id))

            db.refresh(ad)
            self.assertIn("copy model unavailable", ad.analysis_error)
            self.assertIsNone(ad.analysis_summary)
        finally:
            db.close()

    def test_fetch_competitors_reuses_competitor_and_skips_duplicate_ads(self):
        db = make_session()
        try:
            brand = Brand(
                name="Boat",
                website_url="https://example.com",
                category="Audio electronics",
            )
            db.add(brand)
            db.commit()
            db.refresh(brand)

            fake_ads = [
                {
                    "ad_id": "duplicate-1",
                    "copy_text": "Big bass, compact speaker. Shop now.",
                    "image_urls": ["https://cdn.example.com/ad.jpg?oh=abc"],
                },
                {
                    "ad_id": "duplicate-2",
                    "copy_text": "Big bass, compact speaker. Shop now.",
                    "image_urls": ["https://cdn.example.com/ad.jpg?oh=def"],
                }
            ]

            payload = CompetitorFetchRequest(
                brand_id=brand.id,
                competitor_names=["JBL"],
            )

            with patch("routers.competitors.fetch_competitor_ads", return_value=fake_ads):
                first = fetch_competitors_ads(payload, db=db)
                second = fetch_competitors_ads(payload, db=db)

            self.assertEqual(first["competitors_added"], 1)
            self.assertEqual(first["total_ads_fetched"], 1)
            self.assertEqual(first["duplicate_ads_skipped"], 1)

            self.assertEqual(second["competitors_added"], 0)
            self.assertEqual(second["total_ads_fetched"], 0)
            self.assertEqual(second["duplicate_ads_skipped"], 2)

            self.assertEqual(db.query(Competitor).count(), 1)
            self.assertEqual(db.query(Ad).count(), 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
