import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "lbc-finder"))

from analyzers.condition_estimator import estimate_condition
from analyzers.heat_score import calculate_heat_score
from analyzers.margin_estimator import estimate_margin
from analyzers.pipeline import analyze_listing
from analyzers.product_identifier import identify_product
from config.niches import load_premium_stroller_niche
from database.models import ListingAnalysis, MarketStats, RawListing
from database.repositories import ListingRepository


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["LBC_DATA_DIR"] = self.tmpdir.name
        self.niche = load_premium_stroller_niche()

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("LBC_DATA_DIR", None)

    def test_product_identification_uses_title_and_description(self):
        listing = RawListing(
            platform="leboncoin",
            external_id="1",
            title="Pack naissance bébé",
            description="Poussette Cybex Priam avec cosy et nacelle en très bon état",
            price=250,
        )

        analysis = identify_product(listing, self.niche)

        self.assertEqual(analysis.detected_product_type, "poussette")
        self.assertEqual(analysis.detected_brand, "Cybex")
        self.assertEqual(analysis.detected_model, "Priam")
        self.assertIn("cosy", analysis.detected_accessories)
        self.assertGreaterEqual(analysis.identification_confidence, 0.8)

    def test_condition_estimator_detects_condition_and_risks(self):
        condition, risks = estimate_condition(
            "Poussette",
            "Très bon état, quelques rayures, frein à vérifier",
        )

        self.assertEqual(condition, "état correct")
        self.assertIn("vérifier frein", risks)

    def test_market_median_uses_comparable_listings(self):
        repo = ListingRepository()
        for index, price in enumerate([400, 500, 600], start=1):
            listing = RawListing(
                platform="test",
                external_id=str(index),
                title="Cybex Priam",
                price=price,
            )
            repo.upsert_raw(listing)
            repo.update_analysis(
                listing,
                ListingAnalysis(
                    detected_product_type="poussette",
                    detected_brand="Cybex",
                    detected_model="Priam",
                    detected_condition="très bon état",
                ),
                MarketStats(),
                estimate_margin(listing, MarketStats()),
                0,
                "stored",
            )

        stats = repo.market_stats("poussette", "Cybex", "Priam", "très bon état")

        self.assertEqual(stats.comparable_count, 3)
        self.assertEqual(stats.median, 500)

    def test_margin_estimator(self):
        listing = RawListing(platform="test", external_id="1", title="x", price=250)
        margin = estimate_margin(listing, MarketStats(median=500))

        self.assertEqual(margin.estimated_margin_realistic, 215)
        self.assertEqual(margin.total_costs, 35)

    def test_heat_score(self):
        listing = RawListing(platform="test", external_id="1", title="x", price=220)
        analysis = ListingAnalysis(
            detected_product_type="poussette",
            detected_brand="Cybex",
            detected_model="Priam",
            detected_accessories=["cosy", "nacelle"],
            identification_confidence=0.9,
        )
        market = MarketStats(median=500, comparable_count=10)
        margin = estimate_margin(listing, market)

        score, reasons = calculate_heat_score(listing, analysis, market, margin)

        self.assertGreaterEqual(score, 85)
        self.assertIn("Prix très inférieur au marché", reasons)

    def test_pipeline_returns_hot_opportunity_with_fallback_market(self):
        repo = ListingRepository()
        listing = RawListing(
            platform="leboncoin",
            external_id="hot-1",
            title="Poussette bébé",
            description="Cybex Priam trio avec cosy nacelle très bon état",
            price=220,
        )
        repo.upsert_raw(listing)

        opportunity = analyze_listing(listing, self.niche, repo)

        self.assertEqual(opportunity.analysis.detected_brand, "Cybex")
        self.assertEqual(opportunity.analysis.detected_model, "Priam")
        self.assertGreaterEqual(opportunity.heat_score, 75)


if __name__ == "__main__":
    unittest.main()
