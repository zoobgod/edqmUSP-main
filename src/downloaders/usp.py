"""USP Reference Standards document downloader.

Downloads COA (Certificate of Analysis) and related documents
from https://store.usp.org/.
"""

import time
import logging
import re
from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from src.config import USP_USERNAME, USP_PASSWORD, DOWNLOAD_DIR, HEADLESS
from src.browser import create_browser

logger = logging.getLogger(__name__)

USP_BASE_URL = "https://store.usp.org"
USP_LOGIN_URL = f"{USP_BASE_URL}/login"
USP_SEARCH_URL = f"{USP_BASE_URL}/catalogsearch/result/"


@dataclass
class DownloadResult:
    product_code: str
    doc_type: str
    success: bool
    file_path: str = ""
    error: str = ""


@dataclass
class USPDownloader:
    username: str = field(default_factory=lambda: USP_USERNAME)
    password: str = field(default_factory=lambda: USP_PASSWORD)
    download_dir: Path = field(default_factory=lambda: DOWNLOAD_DIR)
    headless: bool = field(default_factory=lambda: HEADLESS)
    _driver: object = field(default=None, repr=False)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        subdir = self.download_dir / "usp"
        subdir.mkdir(parents=True, exist_ok=True)
        self._driver = create_browser(subdir, headless=self.headless)
        logger.info("USP browser started")

    def stop(self):
        if self._driver:
            self._driver.quit()
            self._driver = None
            logger.info("USP browser stopped")

    def login(self) -> bool:
        """Log in to the USP store."""
        if not self.username or not self.password:
            logger.error("USP credentials not configured")
            return False

        try:
            self._driver.get(USP_LOGIN_URL)
            wait = WebDriverWait(self._driver, 15)

            email_field = wait.until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            email_field.clear()
            email_field.send_keys(self.username)

            pass_field = self._driver.find_element(By.ID, "pass")
            pass_field.clear()
            pass_field.send_keys(self.password)

            submit = self._driver.find_element(By.ID, "send2")
            submit.click()

            time.sleep(3)

            if "login" in self._driver.current_url.lower():
                logger.error("USP login failed - still on login page")
                return False

            logger.info("USP login successful")
            return True

        except (TimeoutException, NoSuchElementException) as e:
            logger.error(f"USP login error: {e}")
            return False

    def search_product(self, product_code: str) -> bool:
        """Search for a USP reference standard by catalogue number."""
        normalized_code = self._compact(product_code)
        try:
            search_url = f"{USP_SEARCH_URL}?q={quote_plus(product_code.strip())}"
            self._driver.get(search_url)
            wait = WebDriverWait(self._driver, 15)

            wait.until(lambda d: (
                self._is_product_page(normalized_code)
                or bool(d.find_elements(By.CSS_SELECTOR, ".product-item"))
                or bool(d.find_elements(By.CSS_SELECTOR, ".message.notice, .message.info"))
            ))

            # For exact matches, USP can redirect straight to product details.
            if self._is_product_page(normalized_code):
                logger.info(f"Found USP product: {product_code} (direct hit)")
                return True

            product_link = self._find_matching_result_link(normalized_code)
            if not product_link:
                logger.warning(f"No USP results for: {product_code}")
                return False

            product_link.click()
            time.sleep(2)

            if self._is_product_page(normalized_code):
                logger.info(f"Found USP product: {product_code}")
                return True

            logger.warning(f"USP opened a page that does not match code: {product_code}")
            return False

        except TimeoutException as e:
            logger.error(f"USP search timeout for {product_code}: {e}")
            return False

    def download_document(self, product_code: str, doc_type: str) -> DownloadResult:
        """Download a specific document type for a product.

        Args:
            product_code: USP catalogue number (e.g., "1134357")
            doc_type: One of "COA", "MSDS"
        """
        result = DownloadResult(product_code=product_code, doc_type=doc_type, success=False)

        try:
            link_patterns = {
                "COA": ["certificate of analysis", "coa"],
                "MSDS": ["safety data sheet", "sds", "msds"],
            }
            patterns = link_patterns.get(doc_type.upper())
            if not patterns:
                result.error = f"Unknown document type for USP: {doc_type}"
                return result

            links = self._driver.find_elements(By.TAG_NAME, "a")
            target_link = None
            for link in links:
                text = link.text.lower()
                href = (link.get_attribute("href") or "").lower()
                if any(p in text or p in href for p in patterns):
                    target_link = link
                    break

            if not target_link:
                result.error = f"{doc_type} link not found on page"
                logger.warning(f"{doc_type} link not found for {product_code}")
                return result

            dl_dir = self.download_dir / "usp"
            known_files = {f.name for f in dl_dir.iterdir() if f.is_file()}
            start_time = time.time()
            current_handle = self._driver.current_window_handle
            handles_before = set(self._driver.window_handles)

            target_link.click()
            time.sleep(1.5)

            # Some links open a temporary tab/window before the browser download starts.
            new_handles = [h for h in self._driver.window_handles if h not in handles_before]
            for handle in new_handles:
                try:
                    self._driver.switch_to.window(handle)
                    time.sleep(0.5)
                    self._driver.close()
                except Exception:
                    pass
            self._driver.switch_to.window(current_handle)

            downloaded = self._wait_for_download(
                product_code,
                doc_type,
                known_files=known_files,
                started_at=start_time,
            )
            if downloaded:
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
        """Download COA and MSDS for a given USP product."""
        results = []

        if not self.search_product(product_code):
            for doc_type in ("COA", "MSDS"):
                results.append(DownloadResult(
                    product_code=product_code,
                    doc_type=doc_type,
                    success=False,
                    error="Search failed",
                ))
            return results

        for doc_type in ("COA", "MSDS"):
            result = self.download_document(product_code, doc_type)
            results.append(result)

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
        dl_dir = self.download_dir / "usp"
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

    def _find_matching_result_link(self, normalized_code: str):
        """Pick the product result that matches the requested catalogue number."""
        cards = self._driver.find_elements(By.CSS_SELECTOR, ".product-item")

        # Prefer cards that explicitly contain the requested catalogue number.
        for card in cards:
            if normalized_code and normalized_code in self._compact(card.text):
                links = card.find_elements(By.CSS_SELECTOR, "a.product-item-link")
                if links:
                    return links[0]

        # Fallback to the first visible search hit.
        links = self._driver.find_elements(By.CSS_SELECTOR, "a.product-item-link")
        for link in links:
            if link.is_displayed():
                return link

        return None

    def _is_product_page(self, normalized_code: str) -> bool:
        """Check whether the current USP page is the product details page for the code."""
        current_url = self._driver.current_url.lower()
        if "catalogsearch/result" in current_url:
            return False

        sku_selectors = [
            ".product.attribute.sku .value",
            ".sku .value",
            "[itemprop='sku']",
        ]
        for selector in sku_selectors:
            elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                if normalized_code and self._compact(element.text) == normalized_code:
                    return True

        # Fallback: catalogue number appears in product details text.
        page_text = self._compact(self._driver.page_source)
        return bool(normalized_code and normalized_code in page_text)

    @staticmethod
    def _compact(value: str) -> str:
        """Lowercase and strip non-alphanumeric characters for tolerant matching."""
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())
