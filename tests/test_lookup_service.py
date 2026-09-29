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



class LookupResilienceTests(unittest.TestCase):
    def test_search_stops_and_raises_when_source_does_not_respond(self):
        from src.services.lookup import LookupSourceError, search_lookup_candidates

        class FlakyDownloader:
            calls = 0
            search_error = ""

            def search_products_by_name(self, term, limit=8):
                self.calls += 1
                self.search_error = "EDQM search did not respond in time."
                return []

        downloader = FlakyDownloader()
        with self.assertRaises(LookupSourceError):
            search_lookup_candidates(downloader, "Glycerol Monostearate 40-55 CRS")
        self.assertEqual(downloader.calls, 1)

    def test_enrichment_respects_time_budget(self):
        import time
        from unittest.mock import patch

        import api.index as index

        def slow(_downloader, _code):
            time.sleep(2)
            return {"country_of_origin": "France"}

        started = time.monotonic()
        with patch.object(index, "LOOKUP_ENRICH_BUDGET_SECONDS", 0.3), patch.object(
            index, "_edqm_lookup_enrichment", side_effect=slow
        ):
            result = index._enrich_codes("edqm", ["Y0000001", "Y0000002"])
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(result, {})

    def test_sigma_circuit_breaker_skips_after_failures(self):
        from unittest.mock import patch

        import src.services.cas as cas

        cas._cached_sigma_cas_number.cache_clear()
        cas._sigma_state.update({"failures": 0, "disabled_until": 0.0})
        with patch.object(cas, "_fetch_sigma_html", return_value=("", False)) as fetch:
            self.assertEqual(cas.resolve_cas_number("edqm", object(), "Y0009999"), "")
            self.assertEqual(fetch.call_count, cas.SIGMA_FAILURES_BEFORE_COOLDOWN)
            self.assertEqual(cas.resolve_cas_number("edqm", object(), "Y0009998"), "")
            self.assertEqual(fetch.call_count, cas.SIGMA_FAILURES_BEFORE_COOLDOWN)
        cas._sigma_state.update({"failures": 0, "disabled_until": 0.0})


if __name__ == "__main__":
    unittest.main()
