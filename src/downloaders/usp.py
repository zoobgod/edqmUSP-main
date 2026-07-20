"""USP public document downloader.

Downloads COA, MSDS and COO (country text) for USP catalogue numbers
from public endpoints/pages without login.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import DOWNLOAD_DIR, HEADLESS

logger = logging.getLogger(__name__)

USP_BASE_URL = "https://store.usp.org"
USP_PRODUCT_API = f"{USP_BASE_URL}/ccstore/v1/products"
USP_SEARCH_API = f"{USP_BASE_URL}/ccstore/v1/search"
USP_STATIC_BASE = "https://static.usp.org"

REQUEST_TIMEOUT = (8, 12)
DOWNLOAD_REQUEST_TIMEOUT = (10, 25)
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


@dataclass
class DownloadResult:
    product_code: str
    doc_type: str
    success: bool
    file_path: str = ""
    error: str = ""


@dataclass
class ProductMatch:
    query: str
    product_code: str
    name: str
    source: str = "USP"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class LotInfo:
    lot_number: str = ""
    current: bool = False
    certificate_valid: bool = False
    valid_use_date: str = ""
    origin_country: str = ""
    material_origin: str = ""
    temp_code: str = ""
    hs_code: str = ""


@dataclass
class USPProduct:
    repository_id: str
    display_name: str
    route: str
    category_type: str
    brand: str
    display_sds_link: bool
    country_of_origin: str
    document_link: str
    lots: list[LotInfo]


@dataclass
class USPDownloader:
    download_dir: Path = field(default_factory=lambda: DOWNLOAD_DIR)
    headless: bool = field(default_factory=lambda: HEADLESS)

    _session: requests.Session | None = field(default=None, repr=False)
    _current_product: USPProduct | None = field(default=None, repr=False)
    _last_error: str = field(default="", repr=False)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        (self.download_dir / "usp").mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        retries = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.35,
            status_forcelist=RETRYABLE_STATUS_CODES,
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                # Do not impersonate a browser here. USP's Akamai rules reject
                # incomplete browser fingerprints, while the public API accepts
                # the honest requests user-agent supplied by this session.
                "Accept": "application/json, application/pdf;q=0.9, text/html;q=0.8, */*;q=0.7",
                "Accept-Language": "en-US,en;q=0.8",
            }
        )
        self._session = session
        self._last_error = ""
        logger.info("USP HTTP session started")

    def stop(self):
        if self._session:
            self._session.close()
            self._session = None
            logger.info("USP HTTP session stopped")

    def login(self) -> bool:
        """USP downloads are public; no login needed."""
        logger.info("USP login skipped (public access)")
        return True

    def search_product(self, product_code: str) -> bool:
        """Resolve a USP product from a catalogue number."""
        self._last_error = ""
        product = self._fetch_product(product_code)

        if not product:
            product_id = self._search_product_id(product_code)
            if product_id:
                product = self._fetch_product(product_id)

        if not product:
            logger.warning(
                "USP product lookup failed for %s: %s",
                product_code,
                self._last_error or "Product not found",
            )
            self._current_product = None
            return False

        self._last_error = ""
        self._current_product = product
        logger.info(
            "Resolved USP product %s -> %s (%s)",
            product_code,
            product.repository_id,
            product.display_name,
        )
        return True

    def download_document(self, product_code: str, doc_type: str) -> DownloadResult:
        """Download one document type for a USP product.

        Supported doc types: COA, MSDS, COO.
        """
        result = DownloadResult(product_code=product_code, doc_type=doc_type.upper(), success=False)
        doc_type = doc_type.upper()

        if not self._ensure_current_product(product_code):
            result.error = self._last_error or "Product not found"
            return result

        assert self._current_product is not None
        product = self._current_product

        try:
            if doc_type == "COO":
                file_path = self._write_country_file(product)
                result.success = True
                result.file_path = str(file_path)
                return result

            if doc_type == "COA":
                candidates = self._build_coa_candidates(product)
            elif doc_type in {"MSDS", "SDS"}:
                candidates = self._build_msds_candidates(product)
            else:
                result.error = f"Unknown document type for USP: {doc_type}"
                return result

            downloaded, last_error = self._download_first_available(
                candidates,
                base_name=f"{product.repository_id}_{doc_type}",
            )
            if downloaded:
                result.success = True
                result.file_path = str(downloaded)
                logger.info("Downloaded USP %s for %s: %s", doc_type, product.repository_id, downloaded)
            else:
                if doc_type == "COA":
                    result.error = "COA not publicly available online"
                else:
                    result.error = last_error or f"No valid {doc_type} document URL found"

        except Exception as exc:  # pragma: no cover - safety net
            result.error = str(exc)
            logger.error("Failed USP %s for %s: %s", doc_type, product_code, exc)

        return result

    def download_all(self, product_code: str) -> list[DownloadResult]:
        """Download COA, MSDS and COO for a USP product."""
        results: list[DownloadResult] = []

        if not self.search_product(product_code):
            for doc_type in ("COA", "MSDS", "COO"):
                results.append(
                    DownloadResult(
                        product_code=product_code,
                        doc_type=doc_type,
                        success=False,
                        error="Search failed",
                    )
                )
            return results

        for doc_type in ("COA", "MSDS", "COO"):
            results.append(self.download_document(product_code, doc_type))

        return results

    def search_products_by_name(self, query: str, limit: int = 10) -> list[ProductMatch]:
        session = self._require_session()
        term = query.strip()
        if not term:
            return []

        try:
            resp = session.get(USP_SEARCH_API, params={"Ntt": term}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("USP name search request failed for %s: %s", term, exc)
            return []

        records = payload.get("resultsList", {}).get("records", [])
        matches: list[tuple[int, ProductMatch]] = []
        seen: set[str] = set()
        compact_term = self._compact(term)

        for group in records:
            nested = group.get("records") or []
            for rec in nested:
                attrs = rec.get("attributes", {})
                code = self._first_attr_value(
                    attrs,
                    "product.repositoryId",
                    "product.id",
                    "sku.repositoryId",
                )
                name = self._first_attr_value(
                    attrs,
                    "product.displayName",
                    "sku.displayName",
                )
                if not code or code in seen:
                    continue
                seen.add(code)
                product_match = ProductMatch(
                        query=term,
                        product_code=code,
                        name=name or code,
                        metadata={
                            "price": self._format_price(self._first_attr_value(attrs, "product.listPrice")),
                            "current_lot": self._first_attr_value(attrs, "USPProductType.usp_current_lot_number"),
                            "in_stock": self._format_flag(self._first_attr_value(attrs, "USPProductType.usp_in_stock")),
                            "ready_to_ship": self._format_flag(self._first_attr_value(attrs, "USPProductType.usp_ready_to_ship")),
                            "packing_size": self._first_attr_value(attrs, "USPProductType.usp_packing_size"),
                            "uom": self._first_attr_value(attrs, "USPProductType.usp_uom"),
                            "cas": self._first_attr_value(attrs, "USPProductType.usp_cas_number"),
                            "molecular_formula": self._first_attr_value(attrs, "USPProductType.usp_molecular_formula"),
                            "category_type": self._first_attr_value(attrs, "USPProductType.usp_product_category_type"),
                        },
                )
                matches.append((self._match_rank(term, compact_term, product_match), product_match))

        matches.sort(key=lambda item: (item[0], item[1].name.lower(), item[1].product_code.lower()))
        return [match for _rank, match in matches[:limit]]

    def _match_rank(self, raw_term: str, compact_term: str, match: ProductMatch) -> int:
        name = (match.name or "").strip()
        code = (match.product_code or "").strip()
        compact_name = self._compact(name)
        compact_code = self._compact(code)
        category_type = str((match.metadata or {}).get("category_type", "")).strip().upper()

        if compact_term and compact_code == compact_term:
            return 0
        if compact_term and compact_name == compact_term:
            return 1 if category_type == "RS" else 2
        if compact_term and compact_name.startswith(compact_term):
            return 3 if category_type == "RS" else 4
        if compact_term and compact_term in compact_name:
            return 5 if category_type == "RS" else 6

        raw_lower = raw_term.lower().strip()
        lowered = name.lower()
        if raw_lower and lowered.startswith(raw_lower):
            return 7 if category_type == "RS" else 8
        if raw_lower and raw_lower in lowered:
            return 9 if category_type == "RS" else 10

        return 20 if category_type == "RS" else 30

    def _ensure_current_product(self, product_code: str) -> bool:
        if not self._current_product:
            return self.search_product(product_code)

        current_compact = self._compact(self._current_product.repository_id)
        requested_compact = self._compact(product_code)
        if requested_compact and current_compact == requested_compact:
            return True

        return self.search_product(product_code)

    def get_position_name(self, product_code: str) -> str:
        if self._ensure_current_product(product_code) and self._current_product:
            return self._current_product.display_name or self._current_product.repository_id
        return product_code

    def get_current_batch_number(self, product_code: str) -> str:
        if not (self._ensure_current_product(product_code) and self._current_product):
            return ""

        for lot in self._current_product.lots:
            if lot.current and lot.lot_number:
                return lot.lot_number

        for lot in self._current_product.lots:
            if lot.lot_number:
                return lot.lot_number

        return ""

    def get_cas_number(self, product_code: str) -> str:
        if not self._ensure_current_product(product_code):
            return ""

        target_code = self._current_product.repository_id if self._current_product else product_code
        requested = self._compact(target_code)
        matches = self.search_products_by_name(target_code, limit=8)

        for match in matches:
            if self._compact(match.product_code) != requested:
                continue
            cas = (getattr(match, "metadata", {}) or {}).get("cas", "")
            cas_match = re.search(r"\b\d{2,7}-\d{2}-\d\b", cas or "")
            if cas_match:
                return cas_match.group(0)

        for match in matches:
            cas = (getattr(match, "metadata", {}) or {}).get("cas", "")
            cas_match = re.search(r"\b\d{2,7}-\d{2}-\d\b", cas or "")
            if cas_match:
                return cas_match.group(0)

        return ""

    def get_detail_url(self, product_code: str) -> str:
        if self._ensure_current_product(product_code) and self._current_product:
            return urljoin(USP_BASE_URL, self._current_product.route or "")
        return ""

    def get_last_error(self) -> str:
        """Return a user-facing explanation for the most recent lookup failure."""
        return self._last_error

    def _fetch_product(self, product_code: str) -> USPProduct | None:
        session = self._require_session()
        code = product_code.strip()
        if not code:
            self._last_error = "Enter a USP catalogue number"
            return None

        url = f"{USP_PRODUCT_API}/{quote(code, safe='')}"
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("USP product request failed for %s: %s", code, exc)
            self._last_error = f"USP product service could not be reached: {exc}"
            return self._fetch_product_page(code)

        if resp.status_code == 404:
            self._last_error = "Product not found in the USP catalogue"
            return self._fetch_product_page(code)
        if not resp.ok:
            logger.warning("USP product request returned %s for %s", resp.status_code, code)
            self._last_error = f"USP product service returned HTTP {resp.status_code}"
            return self._fetch_product_page(code)

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("USP product response is not JSON for %s", code)
            self._last_error = "USP product service returned an unreadable response"
            return self._fetch_product_page(code)

        product = self._product_from_payload(payload, code)
        if not product:
            self._last_error = "USP product response did not contain product data"
            return self._fetch_product_page(code)
        return product

    def _fetch_product_page(self, product_code: str) -> USPProduct | None:
        """Fallback to the server-rendered product page when the JSON API changes."""
        session = self._require_session()
        code = product_code.strip()
        url = f"{USP_BASE_URL}/product/{quote(code, safe='')}"
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("USP product page request failed for %s: %s", code, exc)
            self._last_error = f"USP product page could not be reached: {exc}"
            return None

        if resp.status_code == 404:
            self._last_error = "Product not found in the USP catalogue"
            return None
        if not resp.ok:
            self._last_error = f"USP product page returned HTTP {resp.status_code}"
            return None

        product = self._product_from_page_html(resp.text, code)
        if not product:
            self._last_error = "USP product page format was not recognized"
        return product

    def _product_from_page_html(self, page_html: str, product_code: str) -> USPProduct | None:
        state_match = re.search(
            r'window\.state\s*=\s*JSON\.parse\(decodeURI\("([^"]+)"\)\)',
            page_html or "",
        )
        if not state_match:
            return None

        try:
            state = json.loads(unquote(state_match.group(1)))
        except (ValueError, TypeError):
            return None

        requested = self._compact(product_code)
        fallback_payload: dict | None = None

        def find_product(value) -> dict | None:
            nonlocal fallback_payload
            if isinstance(value, dict):
                candidate_id = value.get("repositoryId") or value.get("id")
                if (
                    candidate_id
                    and self._compact(str(candidate_id)) == requested
                    and ("displayName" in value or "usp_lot_details" in value)
                ):
                    if "usp_lot_details" in value:
                        return value
                    if fallback_payload is None:
                        fallback_payload = value
                for child in value.values():
                    found = find_product(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = find_product(child)
                    if found:
                        return found
            return None

        payload = find_product(state) or fallback_payload
        return self._product_from_payload(payload, product_code) if payload else None

    def _product_from_payload(self, payload: dict, fallback_code: str) -> USPProduct | None:
        if not isinstance(payload, dict):
            return None

        repository_id = str(payload.get("repositoryId") or payload.get("id") or fallback_code)
        if not repository_id:
            return None
        route = str(payload.get("route") or f"/product/{repository_id}")
        display_name = str(payload.get("displayName") or repository_id)
        category_type = str(payload.get("usp_product_category_type") or "")
        brand = str(payload.get("brand") or "")
        display_sds_link = bool(payload.get("usp_display_sds_link"))
        country_of_origin = str(payload.get("usp_country_of_origin") or "")
        document_link = str(payload.get("usp_document_link") or "")
        lots = self._parse_lots(str(payload.get("usp_lot_details") or ""))

        return USPProduct(
            repository_id=repository_id,
            display_name=display_name,
            route=route,
            category_type=category_type,
            brand=brand,
            display_sds_link=display_sds_link,
            country_of_origin=country_of_origin,
            document_link=document_link,
            lots=lots,
        )

    def _search_product_id(self, product_code: str) -> str:
        session = self._require_session()
        code = product_code.strip()
        if not code:
            return ""

        try:
            resp = session.get(USP_SEARCH_API, params={"Ntt": code}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("USP search request failed for %s: %s", code, exc)
            self._last_error = f"USP catalogue search failed: {exc}"
            return ""

        records = payload.get("resultsList", {}).get("records", [])
        candidates: list[str] = []

        for group in records:
            nested = group.get("records") or []
            for rec in nested:
                attrs = rec.get("attributes", {})
                for key in ("product.id", "product.repositoryId", "sku.repositoryId"):
                    values = attrs.get(key) or []
                    if values and isinstance(values, list):
                        candidates.append(str(values[0]))

        if not candidates:
            if not self._last_error:
                self._last_error = "Product not found in the USP catalogue"
            return ""

        requested = self._compact(code)
        for candidate in candidates:
            if self._compact(candidate) == requested:
                return candidate

        # Catalogue downloads must never silently fall through to a merely
        # related search result: that could package documents for the wrong item.
        self._last_error = "No exact USP catalogue-number match was found"
        return ""

    def _build_coa_candidates(self, product: USPProduct) -> list[str]:
        product_id = product.repository_id
        lots = self._ordered_lots_for_certificate(product.lots)
        urls: list[str] = []

        # Website-provided direct document link has the highest priority.
        if product.document_link:
            urls.append(urljoin(USP_BASE_URL, product.document_link))

        is_pai_like = product.category_type == "PAI" or (
            product.brand == "STX" and product.category_type != "ARM"
        )
        is_atcc_arm = product.brand == "ATCC" and product.category_type == "ARM"

        if is_atcc_arm:
            for lot in lots:
                urls.append(f"{USP_STATIC_BASE}/pdf/EN/ATCC/CoA/{product_id}-{lot}.pdf")
            urls.append(f"{USP_STATIC_BASE}/pdf/EN/ATCC/PIS/{product_id}.pdf")
        elif is_pai_like:
            for lot in lots:
                urls.append(f"{USP_STATIC_BASE}/pdf/EN/PAI/PIS/{product_id}-{lot}.pdf")
                urls.append(f"{USP_STATIC_BASE}/pdf/EN/referenceStandards/certificates/{product_id}-{lot}.pdf")
        else:
            for lot in lots:
                urls.append(f"{USP_STATIC_BASE}/pdf/EN/referenceStandards/certificates/{product_id}-{lot}.pdf")

        return self._unique(urls)

    def _build_msds_candidates(self, product: USPProduct) -> list[str]:
        product_id = product.repository_id
        urls = [
            f"{USP_STATIC_BASE}/pdf/EN/referenceStandards/msds/{product_id}.pdf",
            f"{USP_STATIC_BASE}/pdf/EN/PAI/msds/{product_id}.pdf",
        ]

        if product.document_link:
            urls.append(urljoin(USP_BASE_URL, product.document_link))

        return self._unique(urls)

    def _download_first_available(self, urls: list[str], base_name: str) -> tuple[Path | None, str]:
        if not urls:
            return None, "No candidate URLs"

        last_error = ""
        for url in urls:
            file_path, error = self._download_url(url, base_name)
            if file_path:
                return file_path, ""
            if error:
                last_error = error

        return None, last_error

    def _download_url(self, url: str, base_name: str) -> tuple[Path | None, str]:
        session = self._require_session()
        try:
            resp = session.get(url, timeout=DOWNLOAD_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return None, f"Request failed for {url}: {exc}"

        if not resp.ok:
            return None, f"HTTP {resp.status_code} for {url}"

        content_type = (resp.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            return None, f"Received HTML instead of document for {url}"

        ext = self._guess_extension(url, content_type)
        if not resp.content:
            return None, f"Received an empty document for {url}"
        if ext == ".pdf" and not resp.content.lstrip().startswith(b"%PDF-"):
            return None, f"Received an invalid PDF payload for {url}"
        filename = f"{self._safe_filename(base_name)}{ext}"
        output = self.download_dir / "usp" / filename
        output.write_bytes(resp.content)
        return output, ""

    def _write_country_file(self, product: USPProduct) -> Path:
        country = self._pick_country(product)
        country = country or "Unknown Country"

        out_dir = self.download_dir / "usp"
        filename = f"{self._safe_filename(country)}.txt"
        output = out_dir / filename

        output.write_text(country + "\n", encoding="utf-8")
        return output

    def _pick_country(self, product: USPProduct) -> str:
        for lot in product.lots:
            if lot.current and lot.origin_country:
                return lot.origin_country

        for lot in product.lots:
            if lot.origin_country:
                return lot.origin_country

        return product.country_of_origin

    def _ordered_lots_for_certificate(self, lots: list[LotInfo]) -> list[str]:
        with_numbers = [lot for lot in lots if lot.lot_number]
        if not with_numbers:
            return []

        ordered = sorted(
            with_numbers,
            key=lambda lot: (
                0 if lot.current and lot.certificate_valid else 1,
                0 if lot.certificate_valid else 1,
                0 if lot.current else 1,
                lot.valid_use_date or "",
            ),
        )

        lot_numbers: list[str] = []
        for lot in ordered:
            if lot.lot_number not in lot_numbers:
                lot_numbers.append(lot.lot_number)
        return lot_numbers

    @staticmethod
    def _parse_lots(raw: str) -> list[LotInfo]:
        if not raw:
            return []

        lots: list[LotInfo] = []
        for chunk in raw.split("##"):
            parts = chunk.split("|")
            if not parts:
                continue

            lot = LotInfo(
                lot_number=parts[0].strip() if len(parts) > 0 else "",
                current=(len(parts) > 1 and parts[1].strip().lower() == "true"),
                certificate_valid=(len(parts) > 2 and parts[2].strip().lower() == "true"),
                valid_use_date=parts[3].strip() if len(parts) > 3 else "",
                origin_country=parts[4].strip() if len(parts) > 4 else "",
                material_origin=parts[5].strip() if len(parts) > 5 else "",
                temp_code=parts[6].strip() if len(parts) > 6 else "",
                hs_code=parts[7].strip() if len(parts) > 7 else "",
            )
            if lot.lot_number:
                lots.append(lot)

        return lots

    @staticmethod
    def _guess_extension(url: str, content_type: str) -> str:
        lowered_url = url.lower()
        if lowered_url.endswith(".pdf") or "application/pdf" in content_type:
            return ".pdf"
        if lowered_url.endswith(".txt") or "text/plain" in content_type:
            return ".txt"
        if lowered_url.endswith(".csv") or "text/csv" in content_type:
            return ".csv"
        return ".bin"

    @staticmethod
    def _safe_filename(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        sanitized = re.sub(r'[\\/*?:"<>|]', "_", normalized).strip().strip(".")
        return sanitized or "file"

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    @staticmethod
    def _format_price(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        try:
            return f"${float(raw.replace(',', '')):,.2f}"
        except ValueError:
            return raw

    @staticmethod
    def _format_flag(value: str) -> str:
        raw = (value or "").strip()
        lowered = raw.lower()
        if lowered in {"true", "y", "yes", "1"}:
            return "Yes"
        if lowered in {"false", "n", "no", "0"}:
            return "No"
        return raw

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    @staticmethod
    def _first_attr_value(attrs: dict, *keys: str) -> str:
        for key in keys:
            values = attrs.get(key) or []
            if values and isinstance(values, list):
                return str(values[0])
        return ""

    def _require_session(self) -> requests.Session:
        if not self._session:
            raise RuntimeError("USPDownloader.start() must be called before use")
        return self._session
