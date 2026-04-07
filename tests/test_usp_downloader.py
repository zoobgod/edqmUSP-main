import unittest

from src.downloaders.usp import ProductMatch, USPDownloader


class USPDownloaderTests(unittest.TestCase):
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
