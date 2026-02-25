"""Shared Selenium browser factory."""

from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from src.config import HEADLESS, DOWNLOAD_DIR


def create_browser(download_dir: Path | None = None, headless: bool | None = None) -> webdriver.Chrome:
    """Create a configured Chrome browser instance."""
    dl_dir = str(download_dir or DOWNLOAD_DIR)
    run_headless = HEADLESS if headless is None else headless

    opts = Options()
    if run_headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")

    prefs = {
        "download.default_directory": dl_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    }
    opts.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.implicitly_wait(10)
    return driver
