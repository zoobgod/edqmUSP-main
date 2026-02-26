"""EDQM public document downloader.

Downloads COA, MSDS and COO from https://crs.edqm.eu/ without login.
COO output keeps original file type and is renamed by detected country.
"""

from __future__ import annotations

import html
import logging
import re
import socket
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import DOWNLOAD_DIR, EDQM_PASSWORD, EDQM_USERNAME, HEADLESS

try:
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover
    curl_requests = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

logger = logging.getLogger(__name__)

EDQM_BASE_URL = "https://crs.edqm.eu"
EDQM_SEARCH_URL = f"{EDQM_BASE_URL}/db/4DCGI/search"
SIGMA_SDS_URL_TEMPLATE = "https://www.sigmaaldrich.com/SE/en/sds/sial/{code}?userType=anonymous"
SIGMA_SDS_URL_TEMPLATE_US = "https://www.sigmaaldrich.com/US/en/sds/sial/{code}?userType=anonymous"
SIGMA_SDS_URL_TEMPLATE_SE_NO_QUERY = "https://www.sigmaaldrich.com/SE/en/sds/sial/{code}"
SIGMA_SDS_URL_TEMPLATE_US_NO_QUERY = "https://www.sigmaaldrich.com/US/en/sds/sial/{code}"
SIGMA_PRODUCT_URL_TEMPLATE = "https://www.sigmaaldrich.com/US/en/product/sial/{code}"
SIGMA_IMPERSONATE = "chrome124"

REQUEST_TIMEOUT = 30
SIGMA_REQUEST_TIMEOUT = (8, 15)
SIGMA_CURL_TIMEOUT = 12


@dataclass
class DownloadResult:
    product_code: str
    doc_type: str
    success: bool
    file_path: str = ""
    error: str = ""


@dataclass
class ProductContext:
    code: str
    name: str = ""
    detail_url: str = ""
    detail_html: str = ""
    links: dict[str, str] = field(default_factory=dict)


@dataclass
class EDQMDownloader:
    username: str = field(default_factory=lambda: EDQM_USERNAME)
    password: str = field(default_factory=lambda: EDQM_PASSWORD)
    download_dir: Path = field(default_factory=lambda: DOWNLOAD_DIR)
    headless: bool = field(default_factory=lambda: HEADLESS)

    _session: requests.Session | None = field(default=None, repr=False)
    _current: ProductContext | None = field(default=None, repr=False)
    _sigma_reachable: bool | None = field(default=None, repr=False)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        (self.download_dir / "edqm").mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        retry = Retry(
            total=1,
            connect=1,
            read=0,
            status=1,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "HEAD"]),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
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
        logger.info("EDQM HTTP session started")

    def stop(self):
        if self._session:
            self._session.close()
            self._session = None
            self._sigma_reachable = None
            logger.info("EDQM HTTP session stopped")

    def login(self) -> bool:
        """EDQM catalogue/documents are public; no login needed."""
        logger.info("EDQM login skipped (public access)")
        return True

    def search_product(self, product_code: str) -> bool:
        """Search EDQM catalogue by exact catalogue code."""
        session = self._require_session()
        code = product_code.strip()
        if not code:
            self._current = None
            return False

        params = {
            "vSelectName": "2",  # Catalogue Code
            "vContains": "2",    # is exactly
            "vtUserName": code,
        }

        try:
            resp = session.get(EDQM_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("EDQM search request failed for %s: %s", code, exc)
            self._current = None
            return False

        detail_href = self._extract_detail_href(resp.text, code)
        if not detail_href:
            logger.warning("No EDQM result detail page for %s", code)
            self._current = None
            return False

        detail_url = urljoin(EDQM_BASE_URL, detail_href)
        detail_html = self._fetch_text(detail_url)
        if not detail_html:
            logger.warning("Failed to load EDQM detail page for %s", code)
            self._current = None
            return False

        links = self._extract_detail_links(detail_url, detail_html)
        name = self._extract_product_name(detail_html) or code
        self._current = ProductContext(
            code=code,
            name=name,
            detail_url=detail_url,
            detail_html=detail_html,
            links=links,
        )
        logger.info("Resolved EDQM product %s -> %s", code, detail_url)
        return True

    def download_document(self, product_code: str, doc_type: str) -> DownloadResult:
        """Download one EDQM document type (COA, MSDS, COO)."""
        result = DownloadResult(product_code=product_code, doc_type=doc_type.upper(), success=False)
        doc_type = doc_type.upper()

        if not self._ensure_current_product(product_code):
            result.error = "Product not found"
            return result

        assert self._current is not None

        if doc_type not in {"COA", "MSDS", "COO"}:
            result.error = f"Unknown document type: {doc_type}"
            return result

        doc_url = self._current.links.get(doc_type, "")
        if doc_type != "MSDS" and not doc_url:
            result.error = f"{doc_type} link not found"
            return result

        try:
            if doc_type == "MSDS":
                downloaded, msds_error = self._download_msds_with_fallback(self._current.code, doc_url)
                if not downloaded:
                    result.error = msds_error or "MSDS download failed"
                    return result
            else:
                downloaded = self._download_binary(doc_url)
            if doc_type == "COO":
                downloaded = self._rename_coo_with_country(downloaded, self._current.code)

            result.success = True
            result.file_path = str(downloaded)
            logger.info("Downloaded EDQM %s for %s: %s", doc_type, self._current.code, downloaded)
            return result

        except Exception as exc:  # pragma: no cover
            result.error = str(exc)
            logger.error("Failed EDQM %s for %s: %s", doc_type, self._current.code, exc)
            return result

    def _download_msds_with_fallback(self, product_code: str, edqm_msds_url: str) -> tuple[Path | None, str]:
        errors: list[str] = []

        if edqm_msds_url:
            try:
                resolved_url = self._resolve_edqm_sds_pdf(edqm_msds_url)
                return self._download_binary(resolved_url), ""
            except Exception as exc:
                errors.append(f"EDQM MSDS failed: {exc}")
                logger.warning("EDQM MSDS failed for %s: %s", product_code, exc)
        else:
            errors.append("EDQM MSDS link not found")

        sigma_path, sigma_error = self._download_sigma_msds(product_code)
        if sigma_path:
            return sigma_path, ""
        if sigma_error:
            errors.append(sigma_error)

        return None, " | ".join(errors)

    def _download_sigma_msds(self, product_code: str) -> tuple[Path | None, str]:
        sigma_code = self._sigma_catalog_code(product_code)
        if not sigma_code:
            return None, "Sigma fallback failed: invalid product code"

        if not self._is_sigma_host_reachable():
            return None, "Sigma SDS fallback failed: host unreachable from runtime"

        errors: list[str] = []
        for sigma_page_url in self._sigma_candidate_urls(sigma_code):
            page_resp, req_error = self._sigma_get(
                sigma_page_url,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            )
            if req_error:
                errors.append(f"{sigma_page_url}: {req_error}")
                continue

            if not page_resp.ok:
                errors.append(f"{sigma_page_url}: HTTP {page_resp.status_code}")
                continue

            content_type = (page_resp.headers.get("content-type") or "").lower()
            if "application/pdf" in content_type:
                return self._save_sigma_msds_file(product_code, page_resp.content), ""

            pdf_url = self._extract_pdf_url_from_html(page_resp.url, page_resp.text)
            if not pdf_url:
                errors.append(f"{sigma_page_url}: no PDF link")
                continue

            downloaded, error = self._download_sigma_pdf_url(product_code, pdf_url)
            if downloaded:
                return downloaded, ""
            if error:
                errors.append(f"{sigma_page_url}: {error}")

        if not errors:
            return None, "Sigma SDS fallback failed"
        return None, "Sigma SDS fallback failed: " + " | ".join(errors)

    def _is_sigma_host_reachable(self) -> bool:
        if self._sigma_reachable is not None:
            return self._sigma_reachable

        try:
            conn = socket.create_connection(("www.sigmaaldrich.com", 443), timeout=3)
            conn.close()
            self._sigma_reachable = True
        except OSError:
            self._sigma_reachable = False

        return self._sigma_reachable

    def _download_sigma_pdf_url(self, product_code: str, pdf_url: str) -> tuple[Path | None, str]:
        pdf_resp, req_error = self._sigma_get(
            pdf_url,
            accept="application/pdf,*/*;q=0.8",
        )
        if req_error:
            return None, f"PDF request failed for {pdf_url}: {req_error}"

        if not pdf_resp.ok:
            return None, f"PDF request returned HTTP {pdf_resp.status_code} for {pdf_url}"

        pdf_content_type = (pdf_resp.headers.get("content-type") or "").lower()
        if "application/pdf" in pdf_content_type or pdf_url.lower().endswith(".pdf"):
            return self._save_sigma_msds_file(product_code, pdf_resp.content), ""

        # Some Sigma links return an intermediate HTML page that contains the final PDF URL.
        nested_pdf_url = self._extract_pdf_url_from_html(pdf_resp.url, pdf_resp.text)
        if not nested_pdf_url or nested_pdf_url == pdf_url:
            return None, "Sigma SDS did not resolve to a PDF document"

        nested_resp, nested_error = self._sigma_get(
            nested_pdf_url,
            accept="application/pdf,*/*;q=0.8",
        )
        if nested_error:
            return None, f"Nested PDF request failed for {nested_pdf_url}: {nested_error}"

        if not nested_resp.ok:
            return None, f"Nested PDF request returned HTTP {nested_resp.status_code} for {nested_pdf_url}"

        nested_type = (nested_resp.headers.get("content-type") or "").lower()
        if "application/pdf" not in nested_type and not nested_pdf_url.lower().endswith(".pdf"):
            return None, "Nested Sigma SDS response is not a PDF"

        return self._save_sigma_msds_file(product_code, nested_resp.content), ""

    def _save_sigma_msds_file(self, product_code: str, content: bytes) -> Path:
        filename = f"{self._safe_filename(product_code)}_MSDS_sigma.pdf"
        destination = self.download_dir / "edqm" / filename
        destination.write_bytes(content)
        logger.info("Downloaded Sigma fallback MSDS for %s: %s", product_code, destination)
        return destination

    def _extract_pdf_url_from_html(self, base_url: str, html_text: str) -> str:
        if not html_text:
            return ""

        # First, use parsed anchors so relative links are handled uniformly.
        candidates: list[str] = []
        for href, text in self._extract_anchors(html_text):
            lower_href = href.lower()
            lower_text = text.lower()
            if ".pdf" in lower_href or "sds" in lower_href or ".pdf" in lower_text:
                candidates.append(urljoin(base_url, href))

        # Fallback for JS-embedded URLs.
        direct_url_matches = re.findall(r'https?://[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?', html_text, flags=re.IGNORECASE)
        for match in direct_url_matches:
            candidates.append(match)

        escaped_url_matches = re.findall(r'https:\\/\\/[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?', html_text, flags=re.IGNORECASE)
        for match in escaped_url_matches:
            candidates.append(match.replace("\\/", "/"))

        normalized: list[str] = []
        for item in candidates:
            if not item:
                continue
            absolute = urljoin(base_url, html.unescape(item.strip()))
            if absolute not in normalized:
                normalized.append(absolute)

        for url in normalized:
            lower = url.lower()
            if "/sds/" in lower and "/en/" in lower:
                return url
        for url in normalized:
            if "/sds/" in url.lower():
                return url
        return normalized[0] if normalized else ""

    @staticmethod
    def _sigma_catalog_code(product_code: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (product_code or "").lower())

    @staticmethod
    def _sigma_candidate_urls(sigma_code: str) -> list[str]:
        urls = [
            SIGMA_SDS_URL_TEMPLATE_SE_NO_QUERY.format(code=sigma_code),
            SIGMA_SDS_URL_TEMPLATE_US_NO_QUERY.format(code=sigma_code),
            SIGMA_SDS_URL_TEMPLATE.format(code=sigma_code),
            SIGMA_SDS_URL_TEMPLATE_US.format(code=sigma_code),
            SIGMA_PRODUCT_URL_TEMPLATE.format(code=sigma_code),
        ]
        unique: list[str] = []
        for url in urls:
            if url not in unique:
                unique.append(url)
        return unique

    def _sigma_get(self, url: str, accept: str) -> tuple[object, str]:
        headers = {
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": EDQM_BASE_URL,
            "Connection": "keep-alive",
        }

        if curl_requests is not None:
            try:
                resp = curl_requests.get(
                    url,
                    headers=headers,
                    timeout=SIGMA_CURL_TIMEOUT,
                    impersonate=SIGMA_IMPERSONATE,
                    allow_redirects=True,
                )
                return resp, ""
            except Exception as exc:  # pragma: no cover
                return None, str(exc)

        session = self._require_session()
        try:
            resp = session.get(url, headers=headers, timeout=SIGMA_REQUEST_TIMEOUT)
            return resp, ""
        except requests.RequestException as exc:
            return None, str(exc)

    def download_all(self, product_code: str) -> list[DownloadResult]:
        """Download COA, MSDS and COO for an EDQM code."""
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
        if not self._current:
            return self.search_product(product_code)

        if self._compact(self._current.code) == self._compact(product_code):
            return True

        return self.search_product(product_code)

    def get_position_name(self, product_code: str) -> str:
        if self._ensure_current_product(product_code) and self._current:
            return self._current.name or self._current.code
        return product_code

    def _extract_detail_href(self, html_text: str, product_code: str) -> str:
        anchors = self._extract_anchors(html_text)
        code_norm = self._compact(product_code)

        for href, text in anchors:
            if "/db/4dcgi/view=" in href.lower() and self._compact(text) == code_norm:
                return href

        for href, _text in anchors:
            if "/db/4dcgi/view=" in href.lower():
                return href

        return ""

    def _extract_detail_links(self, detail_url: str, html_text: str) -> dict[str, str]:
        links: dict[str, str] = {}

        for href, text in self._extract_anchors(html_text):
            lower_href = href.lower()
            lower_text = text.lower()
            absolute = urljoin(detail_url, href)

            if "leaflet" in lower_href or "leaflet" in lower_text:
                links.setdefault("COA", absolute)

            if "safety data sheet" in lower_text or ("sds" in lower_text and "product code" not in lower_text):
                links.setdefault("MSDS", absolute)

            if "oofgoods" in lower_href or "origin of goods" in lower_text:
                links.setdefault("COO", absolute)

        return links

    def _extract_product_name(self, html_text: str) -> str:
        fields = self._extract_detail_fields(html_text)
        for key, value in fields.items():
            if self._compact(key) == "name" and value:
                return value
        return ""

    def _extract_detail_fields(self, html_text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        pattern = re.compile(
            r'<td[^>]*bgcolor=["\']#ffcc00["\'][^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html_text):
            raw_key = re.sub(r"<[^>]+>", " ", match.group(1))
            raw_val = re.sub(r"<[^>]+>", " ", match.group(2))
            key = html.unescape(re.sub(r"\s+", " ", raw_key).strip())
            value = html.unescape(re.sub(r"\s+", " ", raw_val).strip())
            if key and value and key not in fields:
                fields[key] = value
        return fields

    def _extract_anchors(self, html_text: str) -> list[tuple[str, str]]:
        anchors: list[tuple[str, str]] = []
        pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', flags=re.IGNORECASE | re.DOTALL)

        for match in pattern.finditer(html_text):
            href = html.unescape(match.group(1).strip())
            text_raw = re.sub(r"<[^>]+>", " ", match.group(2))
            text = html.unescape(re.sub(r"\s+", " ", text_raw).strip())
            anchors.append((href, text))

        return anchors

    def _resolve_edqm_sds_pdf(self, sds_url: str) -> str:
        session = self._require_session()

        try:
            resp = session.get(sds_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Could not resolve EDQM SDS page %s: %s", sds_url, exc)
            return sds_url

        content_type = (resp.headers.get("content-type") or "").lower()
        if "application/pdf" in content_type:
            return resp.url

        anchors = self._extract_anchors(resp.text)
        pdf_links: list[tuple[str, str]] = []

        for href, text in anchors:
            if ".pdf" in href.lower() or ".pdf" in text.lower():
                pdf_links.append((urljoin(resp.url, href), text))

        if not pdf_links:
            return sds_url

        for href, text in pdf_links:
            if "english" in text.lower() or "_en.pdf" in href.lower():
                return href

        return pdf_links[0][0]

    def _download_binary(self, url: str) -> Path:
        session = self._require_session()
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Request failed for {url}: {exc}") from exc

        content_type = (resp.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            raise RuntimeError(f"Document URL returned HTML instead of file: {url}")

        filename = self._filename_from_response(resp, url)
        destination = self.download_dir / "edqm" / filename
        destination.write_bytes(resp.content)
        return destination

    def _filename_from_response(self, resp: requests.Response, url: str) -> str:
        content_disposition = resp.headers.get("content-disposition", "")

        filename_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
        if filename_match:
            return self._normalize_filename(filename_match.group(1))

        filename_match = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
        if filename_match:
            return self._normalize_filename(filename_match.group(1))

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        for key in ("leaflet", "OofGoods", "oofgoods"):
            if key in query and query[key]:
                return self._normalize_filename(query[key][0])

        basename = Path(parsed.path).name
        if basename:
            return self._normalize_filename(basename)

        content_type = (resp.headers.get("content-type") or "").lower()
        ext = ".pdf" if "application/pdf" in content_type else ".bin"
        return f"download{ext}"

    def _normalize_filename(self, name: str) -> str:
        name = (name or "").strip()
        name = re.sub(r"[\\\r\n\t]", "", name)
        name = re.sub(r'[\\/*?:"<>|]', "_", name)
        return name or "download.bin"

    def _rename_coo_with_country(self, source_path: Path, product_code: str) -> Path:
        """Rename downloaded COO file to country-based filename while keeping original extension."""
        country = self._extract_country_from_file(source_path, product_code) or "Unknown Country"
        suffix = source_path.suffix.lower() or ".pdf"
        filename = f"{self._safe_filename(country)}{suffix}"
        destination = source_path.with_name(filename)

        if destination.exists() and destination.resolve() != source_path.resolve():
            idx = 2
            while True:
                candidate = source_path.with_name(f"{self._safe_filename(country)}_{idx}{suffix}")
                if not candidate.exists():
                    destination = candidate
                    break
                idx += 1

        if source_path.exists() and source_path.resolve() != destination.resolve():
            try:
                source_path.replace(destination)
            except OSError as exc:
                logger.warning("Could not rename COO file %s -> %s: %s", source_path.name, destination.name, exc)
                destination.write_bytes(source_path.read_bytes())
                source_path.unlink(missing_ok=True)

        logger.info("Renamed COO file by country: %s", destination.name)

        return destination

    def _extract_country_from_file(self, source_path: Path, product_code: str = "") -> str:
        text = self._read_text(source_path)
        if not text:
            return ""

        # EDQM COO PDFs contain a table where country is in the last column.
        edqm_table_country = self._extract_edqm_table_country(text, product_code)
        if edqm_table_country:
            return edqm_table_country

        patterns = [
            r"country\s*of\s*origin\s*[:\-]\s*([A-Za-z][A-Za-z\s\-',().]{1,80})",
            r"origin\s*country\s*[:\-]\s*([A-Za-z][A-Za-z\s\-',().]{1,80})",
            r"manufactured\s*in\s*[:\-]?\s*([A-Za-z][A-Za-z\s\-',().]{1,80})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                candidate = self._clean_country_candidate(match.group(1))
                if candidate:
                    return candidate

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for idx, line in enumerate(lines):
            normalized = line.lower()
            if "country of origin" in normalized or "origin country" in normalized:
                after_colon = line.split(":", 1)[1].strip() if ":" in line else ""
                if after_colon:
                    candidate = self._clean_country_candidate(after_colon)
                    if candidate:
                        return candidate
                if idx + 1 < len(lines):
                    candidate = self._clean_country_candidate(lines[idx + 1])
                    if candidate:
                        return candidate

        return ""

    def _extract_edqm_table_country(self, text: str, product_code: str) -> str:
        compact = re.sub(r"\s+", " ", text)

        if product_code:
            escaped_code = re.escape(product_code)
            line_country = self._extract_country_from_code_lines(text, product_code)
            if line_country:
                return line_country

            match = re.search(
                rf"{escaped_code}\s+\d+\s+[A-Za-z][A-Za-z\s\-]{1,40}\s+([A-Za-z][A-Za-z\s\-',().]{{1,60}}?)(?:\s+\*Information|\s+The material|\s+EDQM|\s*$)",
                compact,
                flags=re.IGNORECASE,
            )
            if match:
                candidate = self._clean_country_candidate(match.group(1))
                if candidate:
                    return candidate

            # Alternative table shape:
            # "<code> <batch> <material origin>. <country>"
            match = re.search(
                rf"{escaped_code}\s+\d+\s+.+?\.\s*([A-Za-z][A-Za-z\s\-',()]+?)(?:\s+\*Information|\s+The material|\s+EDQM|\s*$)",
                compact,
                flags=re.IGNORECASE,
            )
            if match:
                candidate = self._clean_country_candidate(match.group(1))
                if candidate:
                    return candidate

        # Fallback without product code.
        match = re.search(
            r"components\s+[A-Z0-9]+\s+\d+\s+[A-Za-z][A-Za-z\s\-]{1,40}\s+([A-Za-z][A-Za-z\s\-',().]{1,60}?)(?:\s+\*Information|\s+The material|\s+EDQM|\s*$)",
            compact,
            flags=re.IGNORECASE,
        )
        if match:
            candidate = self._clean_country_candidate(match.group(1))
            if candidate:
                return candidate

        return ""

    def _extract_country_from_code_lines(self, text: str, product_code: str) -> str:
        code_norm = self._compact(product_code)
        if not code_norm:
            return ""

        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            if code_norm not in self._compact(line):
                continue

            candidate = self._country_from_line_tail(line)
            if candidate:
                return candidate

        return ""

    def _country_from_line_tail(self, line: str) -> str:
        line = re.sub(r"\*.*$", "", line).strip()
        line = line.replace("", " ").replace("•", " ")
        stopwords = {
            "country",
            "origin",
            "preferential",
            "non",
            "components",
            "component",
            "code",
            "catalogue",
            "batch",
            "number",
            "material",
            "information",
            "vegetal",
            "plant",
            "palm",
        }

        segments = [line]
        if "." in line:
            segments.insert(0, line.rsplit(".", 1)[1])
        if ":" in line:
            segments.insert(0, line.rsplit(":", 1)[1])

        token_pattern = re.compile(r"[A-Za-z][A-Za-z'\\-]*(?:\s+[A-Za-z][A-Za-z'\\-]*){0,3}")
        for segment in segments:
            tokens = token_pattern.findall(segment)
            for token in reversed(tokens):
                cleaned = self._clean_country_candidate(token)
                if not cleaned:
                    continue
                if cleaned.lower() in stopwords:
                    continue
                return cleaned

        return ""

    def _read_text(self, source_path: Path) -> str:
        suffix = source_path.suffix.lower()
        if suffix == ".pdf" and PdfReader:
            try:
                reader = PdfReader(str(source_path))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as exc:
                logger.warning("Failed to parse COO PDF %s: %s", source_path.name, exc)

        try:
            raw = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = source_path.read_text(encoding="latin-1", errors="ignore")
        except Exception as exc:
            logger.warning("Failed to read COO file %s: %s", source_path.name, exc)
            return ""

        return re.sub(r"<[^>]+>", " ", raw)

    @staticmethod
    def _clean_country_candidate(value: str) -> str:
        value = (value or "").strip()
        value = re.split(r"[;\n\r]", value)[0]
        value = re.sub(r"\s+", " ", value).strip(" .,:-")
        value = re.sub(r"^(is|the)\s+", "", value, flags=re.IGNORECASE)

        # EDQM COO lines can contain material-origin qualifiers before the country.
        qualifiers = {"synthetic", "vegetal", "plant", "animal", "mineral", "chemical", "biological"}
        parts = value.split()
        while len(parts) > 1 and parts[0].lower() in qualifiers:
            parts = parts[1:]
        value = " ".join(parts)

        if not value:
            return ""
        lowered = value.lower()
        if any(token in lowered for token in ("origin", "country", "component", "catalogue", "batch", "preferential")):
            return ""
        if any(char.isdigit() for char in value):
            return ""
        if len(value.split()) > 6:
            return ""
        return value.title()

    @staticmethod
    def _safe_filename(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        sanitized = re.sub(r'[\\/*?:"<>|]', "_", normalized).strip().strip(".")
        return sanitized or "Unknown_Country"

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _fetch_text(self, url: str) -> str:
        session = self._require_session()
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return ""

    def _require_session(self) -> requests.Session:
        if not self._session:
            raise RuntimeError("EDQMDownloader.start() must be called before use")
        return self._session
