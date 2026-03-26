import unittest

from src.downloaders.edqm import EDQMDownloader


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


if __name__ == "__main__":
    unittest.main()
