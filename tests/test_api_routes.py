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
                "source": "EDQM",
                "code": "Y0001949",
                "name": "RALTEGRAVIR IMPURITY E CRS",
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

    def test_download_post_returns_zip(self):
        fake_zip = b"PK\x03\x04demo"
        fake_manifest = "Batch generated: demo"

        with patch("api.index._download_batch", return_value=(fake_zip, fake_manifest, 1)):
            resp = self.client.post(
                "/api/index.py?page=download",
                data={"source": "edqm", "codes": "G0400006", "doc_types": ["COA", "COO"]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/zip")
        self.assertIn("attachment;", resp.headers.get("content-disposition", ""))
        self.assertEqual(resp.content, fake_zip)

    def test_batch_lookup_post_renders_results(self):
        fake_rows = [
            {
                "query": "I0020000",
                "source": "EDQM",
                "code": "I0020000",
                "name": "IBUPROFEN CRS",
                "batch_number": "6",
                "status": "OK",
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


if __name__ == "__main__":
    unittest.main()
