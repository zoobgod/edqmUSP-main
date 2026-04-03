"""Shared CAS number resolution helpers."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from urllib.parse import quote

import requests

CAS_PATTERN = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
SIGMA_TIMEOUT = 20
SIGMA_IMPERSONATE = "chrome124"


def normalize_cas_number(value: str) -> str:
    match = CAS_PATTERN.search((value or "").strip())
    return match.group(0) if match else ""


def append_cas_to_position_name(position_name: str, cas_number: str) -> str:
    name = (position_name or "").strip()
    cas = normalize_cas_number(cas_number)
    if not name or not cas:
        return name or position_name
    if cas in name:
        return name
    return f"{name} ({cas})"


def resolve_cas_number(source: str, downloader, product_code: str, product_name: str = "") -> str:
    getter = getattr(downloader, "get_cas_number", None)
    if callable(getter):
        try:
            official = normalize_cas_number(getter(product_code) or "")
            if official:
                return official
        except Exception:
            pass

    return sigma_cas_number(source, product_code, product_name)


@lru_cache(maxsize=512)
def sigma_cas_number(source: str, product_code: str, product_name: str = "") -> str:
    code = re.sub(r"[^a-z0-9]+", "", (product_code or "").lower())

    for url in _sigma_product_urls(source, code):
        html_text = _fetch_sigma_html(url)
        if not html_text:
            continue
        cas = _extract_cas_from_sigma_html(html_text)
        if cas:
            return cas

    search_term = (product_name or "").strip()
    if search_term:
        for url in _sigma_search_urls(search_term):
            html_text = _fetch_sigma_html(url)
            if not html_text:
                continue
            cas = _extract_cas_from_sigma_html(html_text)
            if cas:
                return cas

    return ""


def _sigma_product_urls(source: str, sigma_code: str) -> list[str]:
    if not sigma_code:
        return []

    source_key = (source or "").strip().lower()
    if source_key == "usp":
        brands = ("usp", "sial", "supelco")
    else:
        brands = ("sial", "supelco", "usp")

    urls: list[str] = []
    for region in ("SE", "US", "PM"):
        for brand in brands:
            urls.append(f"https://www.sigmaaldrich.com/{region}/en/product/{brand}/{sigma_code}")
    return list(dict.fromkeys(urls))


def _sigma_search_urls(search_term: str) -> list[str]:
    if not search_term:
        return []
    encoded = quote(search_term.strip())
    return [
        f"https://www.sigmaaldrich.com/US/en/search/{encoded}",
        f"https://www.sigmaaldrich.com/SE/en/search/{encoded}",
    ]


def _fetch_sigma_html(url: str) -> str:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
    }

    try:
        from curl_cffi import requests as curl_requests

        resp = curl_requests.get(
            url,
            headers=headers,
            timeout=SIGMA_TIMEOUT,
            impersonate=SIGMA_IMPERSONATE,
            allow_redirects=True,
        )
        if resp.ok and "text/html" in (resp.headers.get("content-type") or "").lower():
            return resp.text
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=headers, timeout=SIGMA_TIMEOUT, allow_redirects=True)
        if resp.ok and "text/html" in (resp.headers.get("content-type") or "").lower():
            return resp.text
    except Exception:
        return ""

    return ""


def _extract_cas_from_sigma_html(html_text: str) -> str:
    if not html_text:
        return ""

    patterns = [
        r'"casNumber"\s*:\s*"([^"]+)"',
        r'"cas_number"\s*:\s*"([^"]+)"',
        r'"casNo"\s*:\s*"([^"]+)"',
        r"CAS(?:\s+Registry)?(?:\s+Number|\s+No\.?|\s+RN)?\s*[:\-]?\s*([0-9]{2,7}-[0-9]{2}-\d)",
    ]

    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            cas = normalize_cas_number(match.group(1))
            if cas:
                return cas

    text = html.unescape(re.sub(r"<[^>]+>", " ", html_text))
    text = re.sub(r"\s+", " ", text).strip()
    match = re.search(
        r"CAS(?:\s+Registry)?(?:\s+Number|\s+No\.?|\s+RN)?\s*[:\-]?\s*([0-9]{2,7}-[0-9]{2}-\d)",
        text,
        flags=re.IGNORECASE,
    )
    return normalize_cas_number(match.group(1)) if match else ""
