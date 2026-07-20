import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import quote

from src.downloaders.usp import ProductMatch, USPDownloader


class USPDownloaderTests(unittest.TestCase):
    def test_session_uses_honest_http_identity_for_usp_edge(self):
        downloader = USPDownloader()
        downloader.start()
        try:
            user_agent = downloader._session.headers.get("User-Agent", "")
            self.assertNotIn("Mozilla/5.0", user_agent)
            self.assertIn("requests", user_agent.lower())
        finally:
            downloader.stop()

    def test_product_page_state_fallback_parses_current_lot(self):
        state = {
            "product": {
                "repositoryId": "1335508",
                "displayName": "Ibuprofen (750 mg)",
                "route": "product/1335508",
                "usp_product_category_type": "RS",
                "usp_display_sds_link": True,
                "usp_country_of_origin": "China",
                "usp_lot_details": "R13060|true|true||China|Chemical Synthesis|UM",
            }
        }
        page_html = (
            '<script>window.state = JSON.parse(decodeURI("'
            + quote(json.dumps(state), safe="")
            + '"))</script>'
        )

        product = USPDownloader()._product_from_page_html(page_html, "1335508")

        self.assertIsNotNone(product)
        self.assertEqual(product.repository_id, "1335508")
        self.assertEqual(product.display_name, "Ibuprofen (750 mg)")
        self.assertEqual(product.lots[0].lot_number, "R13060")
        self.assertTrue(product.lots[0].current)

    def test_search_product_id_rejects_related_non_exact_result(self):
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "resultsList": {
                    "records": [
                        {"records": [{"attributes": {"product.repositoryId": ["1335541"]}}]}
                    ]
                }
            },
        )
        downloader = USPDownloader()
        downloader._session = SimpleNamespace(get=lambda *args, **kwargs: response)

        self.assertEqual(downloader._search_product_id("1335508"), "")
        self.assertIn("exact", downloader.get_last_error().lower())

    def test_invalid_pdf_payload_is_not_saved(self):
        response = SimpleNamespace(
            ok=True,
            headers={"content-type": "application/pdf"},
            content=b"Access denied",
        )
        with TemporaryDirectory() as tmpdir:
            downloader = USPDownloader(download_dir=Path(tmpdir))
            downloader.start()
            downloader._session.get = lambda *args, **kwargs: response
            try:
                path, error = downloader._download_url(
                    "https://static.usp.org/example.pdf",
                    "example",
                )
            finally:
                downloader.stop()

        self.assertIsNone(path)
        self.assertIn("invalid PDF", error)

    def test_match_rank_prefers_exact_rs_product(self):
        downloader = USPDownloader()
        exact_rs = ProductMatch(
            query="Ibuprofen",
            product_code="1335508",
            name="Ibuprofen (750 mg)",
            metadata={"category_type": "RS"},
        )
        impurity = ProductMatch(
            query="Ibuprofen",
            product_code="1A13310",
            name="Hydroxy Ibuprofen (25 mg)",
            metadata={"category_type": "PAI"},
        )

        exact_rank = downloader._match_rank("Ibuprofen", downloader._compact("Ibuprofen"), exact_rs)
        impurity_rank = downloader._match_rank("Ibuprofen", downloader._compact("Ibuprofen"), impurity)

        self.assertLess(exact_rank, impurity_rank)


if __name__ == "__main__":
    unittest.main()
