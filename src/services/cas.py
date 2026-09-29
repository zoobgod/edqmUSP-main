"""Shared CAS number resolution helpers."""

from __future__ import annotations

import html
import re
import threading
import time
from functools import lru_cache
from urllib.parse import quote

import requests

CAS_PATTERN = re.compile(r"\b\d{2,7}-\d{2}-\d\b")
SIGMA_TIMEOUT = 8
SIGMA_IMPERSONATE = "chrome124"
# Sigma often blocks or stalls automated requests. Cap the time spent per lookup and
# stop calling it for a while once it fails, so one slow host cannot stall a whole batch.
SIGMA_CALL_BUDGET_SECONDS = 12
SIGMA_COOLDOWN_SECONDS = 600
SIGMA_FAILURES_BEFORE_COOLDOWN = 2

_sigma_lock = threading.Lock()
_sigma_state = {"failures": 0, "disabled_until": 0.0}


def _sigma_available() -> bool:
    with _sigma_lock:
        return time.monotonic() >= _sigma_state["disabled_until"]


def _record_sigma_result(ok: bool) -> None:
    with _sigma_lock:
        if ok:
            _sigma_state["failures"] = 0
            return
        _sigma_state["failures"] += 1
        if _sigma_state["failures"] >= SIGMA_FAILURES_BEFORE_COOLDOWN:
            _sigma_state["disabled_until"] = time.monotonic() + SIGMA_COOLDOWN_SECONDS
            _sigma_state["failures"] = 0


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


def resolve_cas_number(
    source: str,
    downloader,
    product_code: str,
    product_name: str = "",
    allow_name_fallback: bool = True,
) -> str:
    getter = getattr(downloader, "get_cas_number", None)
    if callable(getter):
        try:
            official = normalize_cas_number(getter(product_code) or "")
            if official:
                return official
        except Exception:
            pass

    if not _sigma_available():
        return ""
    return sigma_cas_number(source, product_code, product_name, allow_name_fallback)


class _SigmaUnavailable(Exception):
    """Raised to skip caching when Sigma could not be queried (vs. answered with no CAS)."""


def sigma_cas_number(
    source: str,
    product_code: str,
    product_name: str = "",
    allow_name_fallback: bool = True,
) -> str:
    try:
        return _cached_sigma_cas_number(source, product_code, product_name, allow_name_fallback)
    except _SigmaUnavailable:
        return ""


@lru_cache(maxsize=512)
def _cached_sigma_cas_number(
    source: str,
    product_code: str,
    product_name: str = "",
    allow_name_fallback: bool = True,
) -> str:
    code = re.sub(r"[^a-z0-9]+", "", (product_code or "").lower())
    deadline = time.monotonic() + SIGMA_CALL_BUDGET_SECONDS

    urls = list(_sigma_product_urls(source, code))
    search_term = (product_name or "").strip()
    if allow_name_fallback and search_term:
        urls += _sigma_search_urls(search_term)

    reached = False
    for url in urls:
        if time.monotonic() >= deadline or not _sigma_available():
            break
        html_text, ok = _fetch_sigma_html(url)
        _record_sigma_result(ok)
        reached = reached or ok
        if not html_text:
            continue
        cas = _extract_cas_from_sigma_html(html_text)
        if cas:
            return cas

    if not reached:
        raise _SigmaUnavailable()
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


def _fetch_sigma_html(url: str) -> tuple[str, bool]:
    """Return (html, host_responded). A 404 counts as a response; timeouts and blocks do not."""
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
        return _sigma_response_html(resp)
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=headers, timeout=SIGMA_TIMEOUT, allow_redirects=True)
        return _sigma_response_html(resp)
    except Exception:
        return "", False


def _sigma_response_html(resp) -> tuple[str, bool]:
    status = getattr(resp, "status_code", 0)
    if status in (403, 429) or status >= 500:
        return "", False
    if resp.ok and "text/html" in (resp.headers.get("content-type") or "").lower():
        return resp.text, True
    return "", True


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
