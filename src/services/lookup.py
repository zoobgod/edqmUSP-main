"""Shared lookup query normalization and candidate expansion."""

from __future__ import annotations

import html
import re


def clean_lookup_fragment(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"\([^)]*(?:edqm|usp)[^)]*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]*(?:edqm|usp)[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[-|]\s*(?:edqm|usp)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-_/|,;")
    return text


def strip_lookup_suffix_tokens(value: str) -> str:
    tokens = [token for token in re.split(r"\s+", value or "") if token]
    while tokens and tokens[-1].rstrip(".,").upper() in {"RS", "CRS"}:
        tokens.pop()
    return " ".join(tokens).strip()


def strip_lookup_quantity_tokens(value: str) -> str:
    text = value or ""
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:mg|g|kg|mcg|ug|μg|ml|l|mmol|mol|ppm|%)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    # Only strip standalone numbers if the result still contains alphabetic content
    candidate = re.sub(r"\b\d+(?:[.,]\d+)?\b", " ", text)
    candidate = re.sub(r"\s+", " ", candidate).strip(" \t\r\n-_/|,;")
    if candidate:
        return candidate
    # If stripping numbers removes everything, return the quantity-only stripped version
    return re.sub(r"\s+", " ", text).strip(" \t\r\n-_/|,;")


def prefix_lookup_candidates(value: str, min_words: int = 2, max_words: int = 5) -> list[str]:
    words = [word for word in re.split(r"\s+", value or "") if word]
    if len(words) < min_words:
        return []

    upper_bound = min(len(words), max_words)
    prefixes: list[str] = []
    for size in range(upper_bound, min_words - 1, -1):
        prefix = " ".join(words[:size]).strip()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def lookup_query_candidates(raw_query: str) -> list[str]:
    base = clean_lookup_fragment(raw_query)
    if not base:
        return []

    split_parts = re.split(r"\s*[/|;]\s*", base)
    candidates: list[str] = []

    def add(value: str):
        cleaned = clean_lookup_fragment(value)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

        stripped = strip_lookup_suffix_tokens(cleaned)
        if stripped and stripped not in candidates:
            candidates.append(stripped)

        quantity_stripped = strip_lookup_quantity_tokens(stripped or cleaned)
        if quantity_stripped and quantity_stripped not in candidates:
            candidates.append(quantity_stripped)

        for prefix in prefix_lookup_candidates(quantity_stripped or stripped or cleaned):
            if prefix not in candidates:
                candidates.append(prefix)

    latin_parts = [part for part in split_parts if re.search(r"[A-Za-z]", part or "")]
    for part in latin_parts:
        add(part)

    add(base)

    for part in split_parts:
        add(part)

    if not candidates:
        add(raw_query)

    return candidates


def search_lookup_candidates(downloader, raw_query: str, limit: int = 8) -> tuple[list, str]:
    attempted: list[str] = []
    for candidate in lookup_query_candidates(raw_query):
        attempted.append(candidate)
        matches = downloader.search_products_by_name(candidate, limit=limit)
        if matches:
            return matches, candidate

    fallback = attempted[0] if attempted else raw_query.strip()
    return [], fallback
