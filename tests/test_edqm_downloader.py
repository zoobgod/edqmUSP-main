import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.downloaders.edqm import EDQMDownloader, ProductContext


class EDQMDownloaderTests(unittest.TestCase):
    def test_extract_detail_links_accepts_safety_data_statement(self):
        downloader = EDQMDownloader()
        html = """
        <html><body>
          <a href="https://sds.edqm.eu/?ref=201700545">Click to download Safety Data Statement</a>
          <a href="/db/4DCGI/leaflet?leaflet=Y0001153_1.pdf">click to download the leaflet</a>
          <a href="/db/4DCGI/OofGoods?OofGoods=Y0001153_CO_1.pdf">click to download Origin Of Goods.pdf</a>
        </body></html>
        """

        links = downloader._extract_detail_links("https://crs.edqm.eu/db/4DCGI/View=Y0001153", html)

        self.assertEqual(links.get("MSDS"), "https://sds.edqm.eu/?ref=201700545")
        self.assertIn("COA", links)
        self.assertIn("COO", links)

    def test_sigma_candidate_urls_include_supelco_variant(self):
        urls = EDQMDownloader._sigma_candidate_urls("y0002266")

        self.assertIn("https://www.sigmaaldrich.com/SE/en/product/supelco/y0002266", urls)
        self.assertIn("https://www.sigmaaldrich.com/SE/en/sds/supelco/y0002266?userType=anonymous", urls)

    def test_country_from_line_tail_skips_false_single_letter_and_material_words(self):
        downloader = EDQMDownloader()

        self.assertEqual(downloader._country_from_line_tail("Y0001153 1 Human: purified human"), "")
        self.assertEqual(downloader._country_from_line_tail("immunoglobulins"), "")
        self.assertEqual(downloader._country_from_line_tail("Great Britain"), "Great Britain")

    def test_sigma_error_summary_collapses_dns_failures(self):
        downloader = EDQMDownloader()
        message = downloader._summarize_sigma_errors(
            [
                "https://www.sigmaaldrich.com/SE/en/sds/sial/g0400006: Failed to perform, curl: (6) Could not resolve host: www.sigmaaldrich.com",
                "https://www.sigmaaldrich.com/US/en/sds/sial/g0400006: Failed to perform, curl: (6) Could not resolve host: www.sigmaaldrich.com",
            ]
        )

        self.assertEqual(message, "Sigma SDS fallback failed: Sigma host could not be resolved from the runtime")

    def test_get_country_of_origin_parses_coo_once_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = EDQMDownloader(download_dir=Path(tmpdir))
            downloader._current = ProductContext(
                code="G0400006",
                links={"COO": "https://crs.edqm.eu/db/4DCGI/OofGoods?OofGoods=G0400006_CO_2.pdf"},
            )
            calls = []

            def fake_download(url, destination_dir=None):
                calls.append(url)
                path = destination_dir / "G0400006_CO_2.txt"
                path.write_text(
                    "Code catalogue Batch number Material origin Country of non-preferential origin for components\n"
                    "G0400006 2 Vegetal/plant France\n"
                    "*Information applies to batch number and sub-batches.\n"
                )
                return path

            with patch.object(downloader, "_download_binary", side_effect=fake_download):
                self.assertEqual(downloader.get_country_of_origin("G0400006"), "France")
                self.assertEqual(downloader.get_country_of_origin("G0400006"), "France")

            self.assertEqual(len(calls), 1)
            self.assertEqual(list((Path(tmpdir) / "edqm").glob("*")), [])

    def test_get_country_of_origin_without_coo_link(self):
        downloader = EDQMDownloader()
        downloader._current = ProductContext(code="Y0000001", links={})

        self.assertEqual(downloader.get_country_of_origin("Y0000001"), "")


if __name__ == "__main__":
    unittest.main()
