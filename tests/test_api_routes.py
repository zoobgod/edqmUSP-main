import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.index import app


class ApiRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_lookup_post_renders_results(self):
        fake_rows = [
            {
                "query": "Raltegravir Impurity E RS / Ралтегравир примесь E CO (EDQM)",
                "matched_on": "Raltegravir Impurity E",
                "match_type": "Normalized",
                "rank": "1",
                "source": "EDQM",
                "code": "Y0001949",
                "name": "RALTEGRAVIR IMPURITY E CRS",
                "enrichment": {
                    "availability": "Available",
                    "price": "90 EUR",
                    "current_batch": "2",
                    "unit_quantity": "10 MG",
                },
            }
        ]

        with patch("api.index._lookup_catalogue_numbers", return_value=fake_rows):
            resp = self.client.post(
                "/api/index.py?page=lookup",
                data={"source": "edqm", "names": fake_rows[0]["query"]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Y0001949", resp.text)
        self.assertIn("Copy Catalogue Numbers", resp.text)
        self.assertIn("Matched On", resp.text)
        self.assertIn("Normalized", resp.text)
        self.assertIn("View details", resp.text)

    def test_download_post_renders_summary_page(self):
        fake_result = {
            "zip_bytes": b"PK\x03\x04demo",
            "manifest_text": "Batch generated: demo",
            "position_count": 1,
            "rows": [
                {
                    "code": "G0400006",
                    "source": "EDQM",
                    "name": "GLYCEROL MONOSTEARATE 40-55 CRS",
                    "summary": {
                        "name": "GLYCEROL MONOSTEARATE 40-55 CRS",
                        "current_batch": "4",
                        "price": "90 EUR",
                        "availability": "Available",
                        "storage": "+5°C+/-3°C",
                    },
                    "doc_results": {
                        "COA": {"status": "OK", "file_name": "coa.pdf", "error": ""},
                        "COO": {"status": "OK", "file_name": "France.pdf", "error": ""},
                    },
                    "notes": ["All requested documents downloaded."],
                    "timeline": [{"label": "Search", "status": "ok"}],
                }
            ],
        }

        with patch("api.index._download_batch", return_value=fake_result):
            resp = self.client.post(
                "/api/index.py?page=download",
                data={"source": "edqm", "codes": "G0400006", "doc_types": ["COA", "COO"]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Download Batch ZIP", resp.text)
        self.assertIn("Download Summary", resp.text)
        self.assertIn("G0400006", resp.text)
        self.assertIn("page=download-file", resp.text)

    def test_download_file_route_returns_zip(self):
        fake_result = {
            "zip_bytes": b"PK\x03\x04demo",
            "manifest_text": "Batch generated: demo",
            "position_count": 1,
            "rows": [],
        }
        with patch("api.index._download_batch", return_value=fake_result):
            resp = self.client.post(
                "/api/index.py?page=download-file",
                data={"source": "edqm", "codes": "G0400006", "doc_types": ["COA", "COO"]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/zip")
        self.assertIn("attachment;", resp.headers.get("content-disposition", ""))
        self.assertEqual(resp.content, b"PK\x03\x04demo")

    def test_batch_lookup_post_renders_results(self):
        fake_rows = [
            {
                "query": "I0020000",
                "source": "EDQM",
                "code": "I0020000",
                "name": "IBUPROFEN CRS",
                "batch_number": "6",
                "status": "OK",
                "summary": {
                    "current_batch": "6",
                    "availability": "Available",
                    "price": "90 EUR",
                    "storage": "+5°C+/-3°C",
                    "dispatching": "Ambient temp.",
                },
                "detail_url": "https://crs.edqm.eu/db/4DCGI/View=I0020000",
                "actionability": "Current",
                "actionability_class": "ok",
            }
        ]

        with patch("api.index._lookup_current_batches", return_value=fake_rows):
            resp = self.client.post(
                "/api/index.py?page=batches",
                data={"source": "edqm", "codes": "I0020000"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Current Batch Results", resp.text)
        self.assertIn("Copy Batch Numbers", resp.text)
        self.assertIn("IBUPROFEN CRS", resp.text)
        self.assertIn("6", resp.text)
        self.assertIn("Availability", resp.text)
        self.assertIn("Open", resp.text)


if __name__ == "__main__":
    unittest.main()
