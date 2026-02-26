"""USP public document downloader.

Downloads COA, MSDS and COO (country text) for USP catalogue numbers
from public endpoints/pages without login.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests

from src.config import DOWNLOAD_DIR, HEADLESS, USP_PASSWORD, USP_USERNAME

logger = logging.getLogger(__name__)

USP_BASE_URL = "https://store.usp.org"
USP_PRODUCT_API = f"{USP_BASE_URL}/ccstore/v1/products"
USP_SEARCH_API = f"{USP_BASE_URL}/ccstore/v1/search"
USP_STATIC_BASE = "https://static.usp.org"

REQUEST_TIMEOUT = 30


@dataclass
class DownloadResult:
    product_code: str
    doc_type: str
    success: bool
    file_path: str = ""
    error: str = ""


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
    username: str = field(default_factory=lambda: USP_USERNAME)
    password: str = field(default_factory=lambda: USP_PASSWORD)
    download_dir: Path = field(default_factory=lambda: DOWNLOAD_DIR)
    headless: bool = field(default_factory=lambda: HEADLESS)

    _session: requests.Session | None = field(default=None, repr=False)
    _current_product: USPProduct | None = field(default=None, repr=False)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        (self.download_dir / "usp").mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/132.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
            }
        )
        self._session = session
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
        product = self._fetch_product(product_code)

        if not product:
            product_id = self._search_product_id(product_code)
            if product_id:
                product = self._fetch_product(product_id)

        if not product:
            logger.warning(f"USP product not found: {product_code}")
            self._current_product = None
            return False

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
            result.error = "Product not found"
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

    def _fetch_product(self, product_code: str) -> USPProduct | None:
        session = self._require_session()
        code = product_code.strip()
        if not code:
            return None

        url = f"{USP_PRODUCT_API}/{code}"
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("USP product request failed for %s: %s", code, exc)
            return None

        if resp.status_code == 404:
            return None
        if not resp.ok:
            logger.warning("USP product request returned %s for %s", resp.status_code, code)
            return None

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("USP product response is not JSON for %s", code)
            return None

        repository_id = str(payload.get("repositoryId") or payload.get("id") or code)
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
            return ""

        requested = self._compact(code)
        for candidate in candidates:
            if self._compact(candidate) == requested:
                return candidate

        return candidates[0]

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
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return None, f"Request failed for {url}: {exc}"

        if not resp.ok:
            return None, f"HTTP {resp.status_code} for {url}"

        content_type = (resp.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            return None, f"Received HTML instead of document for {url}"

        ext = self._guess_extension(url, content_type)
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
    def _unique(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return unique_values

    def _require_session(self) -> requests.Session:
        if not self._session:
            raise RuntimeError("USPDownloader.start() must be called before use")
        return self._session
