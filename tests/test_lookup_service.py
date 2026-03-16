import unittest

from src.services.lookup import lookup_query_candidates, search_lookup_candidates


class _FakeDownloader:
    def __init__(self, mapping):
        self.mapping = mapping
        self.queries = []

    def search_products_by_name(self, query, limit=8):
        self.queries.append((query, limit))
        return list(self.mapping.get(query, []))


class LookupServiceTests(unittest.TestCase):
    def test_candidates_strip_noise_and_suffixes(self):
        raw = "Raltegravir Impurity E RS / Raltegravir impurity E co (EDQM)"
        candidates = lookup_query_candidates(raw)
        self.assertIn("Raltegravir Impurity E RS", candidates)
        self.assertIn("Raltegravir Impurity E", candidates)
        self.assertGreaterEqual(len(candidates), 2)

    def test_candidates_strip_quantities_and_add_prefixes(self):
        raw = "Sodium taurocholate BRP 10000 mg / Sodium taurocholate BRP"
        candidates = lookup_query_candidates(raw)
        self.assertIn("Sodium taurocholate BRP", candidates)
        self.assertIn("Sodium taurocholate", candidates)

    def test_search_lookup_candidates_tries_in_order(self):
        raw = "Sodium taurocholate BRP 10000 mg"
        downloader = _FakeDownloader(
            {
                "Sodium taurocholate BRP": ["S0900000"],
            }
        )

        matches, used = search_lookup_candidates(downloader, raw, limit=5)

        self.assertEqual(matches, ["S0900000"])
        self.assertEqual(used, "Sodium taurocholate BRP")
        self.assertGreaterEqual(len(downloader.queries), 1)


if __name__ == "__main__":
    unittest.main()
