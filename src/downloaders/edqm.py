"""EDQM CRS document downloader.

Downloads COA (Certificate of Analysis), MSDS (Material Safety Data Sheet),
and COO (Certificate of Origin) from https://crs.edqm.eu/.
"""

import time
import logging
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from src.config import EDQM_USERNAME, EDQM_PASSWORD, DOWNLOAD_DIR, HEADLESS
from src.browser import create_browser

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency import
    PdfReader = None

logger = logging.getLogger(__name__)

EDQM_BASE_URL = "https://crs.edqm.eu"
EDQM_LOGIN_URL = f"{EDQM_BASE_URL}/db/4DCGI/Login"
EDQM_SEARCH_URL = f"{EDQM_BASE_URL}/db/4DCGI/Search"


@dataclass
class DownloadResult:
    product_code: str
    doc_type: str
    success: bool
    file_path: str = ""
    error: str = ""


@dataclass
class EDQMDownloader:
    username: str = field(default_factory=lambda: EDQM_USERNAME)
    password: str = field(default_factory=lambda: EDQM_PASSWORD)
    download_dir: Path = field(default_factory=lambda: DOWNLOAD_DIR)
    headless: bool = field(default_factory=lambda: HEADLESS)
    _driver: object = field(default=None, repr=False)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        subdir = self.download_dir / "edqm"
        subdir.mkdir(parents=True, exist_ok=True)
        self._driver = create_browser(subdir, headless=self.headless)
        logger.info("EDQM browser started")

    def stop(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
            logger.info("EDQM browser stopped")

    def login(self) -> bool:
        """Log in to the EDQM CRS portal."""
        if not self.username or not self.password:
            logger.error("EDQM credentials not configured")
            return False

        try:
            self._driver.get(EDQM_LOGIN_URL)
            wait = WebDriverWait(self._driver, 15)

            user_field = wait.until(
                EC.presence_of_element_located((By.NAME, "vLogin"))
            )
            user_field.clear()
            user_field.send_keys(self.username)

            pass_field = self._driver.find_element(By.NAME, "vPassword")
            pass_field.clear()
            pass_field.send_keys(self.password)

            submit = self._driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
            submit.click()

            time.sleep(3)

            if "Login" in self._driver.title:
                logger.error("EDQM login failed - still on login page")
                return False

            logger.info("EDQM login successful")
            return True

        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"EDQM login error: {e}")
            return False

    def search_product(self, product_code: str) -> bool:
        """Search for a product by its catalogue code."""
        try:
            self._driver.get(EDQM_SEARCH_URL)
            wait = WebDriverWait(self._driver, 15)

            search_field = wait.until(
                EC.presence_of_element_located((By.NAME, "vSearchCriteria"))
            )
            search_field.clear()
            search_field.send_keys(product_code)

            submit = self._driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
            submit.click()

            time.sleep(3)
            logger.info(f"Searched for EDQM product: {product_code}")
            return True

        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"EDQM search error for {product_code}: {e}")
            return False

    def download_document(self, product_code: str, doc_type: str) -> DownloadResult:
        """Download a specific document type for a product.

        Args:
            product_code: EDQM catalogue code (e.g., "Y0001532")
            doc_type: One of "COA", "MSDS", "COO"
        """
        result = DownloadResult(product_code=product_code, doc_type=doc_type, success=False)

        try:
            link_texts = {
                "COA": "Certificate of Analysis",
                "MSDS": "Safety Data Sheet",
                "COO": "Certificate of Origin",
            }
            link_text = link_texts.get(doc_type.upper())
            if not link_text:
                result.error = f"Unknown document type: {doc_type}"
                return result

            wait = WebDriverWait(self._driver, 10)
            link = wait.until(
                EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, link_text))
            )

            dl_dir = self.download_dir / "edqm"
            known_files = {f.name for f in dl_dir.iterdir() if f.is_file()}
            start_time = time.time()
            link.click()

            downloaded = self._wait_for_download(
                product_code,
                doc_type,
                known_files=known_files,
                started_at=start_time,
            )
            if downloaded:
                if doc_type.upper() == "COO":
                    downloaded = self._convert_coo_to_country_txt(downloaded, product_code)
                result.success = True
                result.file_path = str(downloaded)
                logger.info(f"Downloaded {doc_type} for {product_code}: {downloaded}")
            else:
                result.error = "Download timed out"
                logger.warning(f"Download timed out for {doc_type} of {product_code}")

        except Exception as e:
            result.error = str(e)
            logger.error(f"Failed to download {doc_type} for {product_code}: {e}")

        return result

    def download_all(self, product_code: str) -> list[DownloadResult]:
        """Download COA, MSDS, and COO for a given product."""
        results = []

        if not self.search_product(product_code):
            for doc_type in ("COA", "MSDS", "COO"):
                results.append(DownloadResult(
                    product_code=product_code,
                    doc_type=doc_type,
                    success=False,
                    error="Search failed",
                ))
            return results

        for doc_type in ("COA", "MSDS", "COO"):
            result = self.download_document(product_code, doc_type)
            results.append(result)
            self._driver.back()
            time.sleep(1)

        return results

    def _wait_for_download(
        self,
        product_code: str,
        doc_type: str,
        timeout: int = 30,
        known_files: set[str] | None = None,
        started_at: float | None = None,
    ) -> Path | None:
        """Wait for a file to finish downloading."""
        dl_dir = self.download_dir / "edqm"
        known_files = known_files or set()
        started_at = started_at or time.time()
        start = time.time()
        while time.time() - start < timeout:
            for f in dl_dir.iterdir():
                if f.suffix == ".crdownload":
                    continue
                if not f.is_file():
                    continue
                is_new_file = f.name not in known_files
                is_new_version = f.stat().st_mtime >= started_at - 1
                if not (is_new_file or is_new_version):
                    continue
                if (
                    product_code.lower() in f.name.lower()
                    or doc_type.lower() in f.name.lower()
                    or f.suffix.lower() in {".pdf", ".txt"}
                ):
                    return f
            time.sleep(1)
        return None

    def _convert_coo_to_country_txt(self, source_path: Path, product_code: str) -> Path:
        """Create COO output as a country-named .txt file and remove original file."""
        country = self._extract_country_from_file(source_path) or "Unknown Country"
        filename = f"{self._safe_filename(country)}.txt"
        destination = source_path.with_name(filename)

        # Avoid accidental overwrite when multiple products share the same country.
        if destination.exists() and destination.resolve() != source_path.resolve():
            destination = source_path.with_name(
                f"{self._safe_filename(country)}_{self._safe_filename(product_code)}.txt"
            )

        destination.write_text(country + "\n", encoding="utf-8")
        logger.info(f"Generated COO country file: {destination.name}")

        if source_path.exists() and source_path.resolve() != destination.resolve():
            try:
                source_path.unlink()
            except OSError as exc:
                logger.warning(f"Could not remove original COO file {source_path.name}: {exc}")

        return destination

    def _extract_country_from_file(self, source_path: Path) -> str:
        text = self._read_text(source_path)
        if not text:
            return ""

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

        # Fallback: inspect nearby lines if the value is on the next line.
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

    def _read_text(self, source_path: Path) -> str:
        suffix = source_path.suffix.lower()
        if suffix == ".pdf" and PdfReader:
            try:
                reader = PdfReader(str(source_path))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as exc:
                logger.warning(f"Failed to parse COO PDF {source_path.name}: {exc}")

        try:
            raw = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = source_path.read_text(encoding="latin-1", errors="ignore")
        except Exception as exc:
            logger.warning(f"Failed to read COO file {source_path.name}: {exc}")
            return ""

        return re.sub(r"<[^>]+>", " ", raw)

    @staticmethod
    def _clean_country_candidate(value: str) -> str:
        value = (value or "").strip()
        value = re.split(r"[;\n\r]", value)[0]
        value = re.sub(r"\s+", " ", value).strip(" .,:-")
        value = re.sub(r"^(is|the)\s+", "", value, flags=re.IGNORECASE)

        if not value:
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
