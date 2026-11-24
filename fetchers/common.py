"""Shared pieces for all fetchers: the Paper record, an HTTP session with retries, text helpers."""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("journal")

USER_AGENT = "read-journal/2.0 (personal research digest)"


@dataclass
class Paper:
    key: str                     # stable id, e.g. "arxiv:2611.12345", "or:AbCdEf", "url:https://..."
    title: str
    abstract: str = ""
    url: str = ""                # landing page
    pdf_url: str = ""
    code_url: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""          # ISO date "YYYY-MM-DD" when known, else "YYYY"
    source: str = ""             # human label: "arXiv", "NeurIPS 2025", "HF Daily", "BAIR blog"
    kind: str = "paper"          # "paper" | "blog"
    status: str = ""             # conference decision: Oral / Spotlight / Poster ...
    extra: dict = field(default_factory=dict)  # upvotes, likes, keywords, ...


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ARXIV_ID = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d])")


def clean_text(s: str | None, limit: int | None = None) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not s:
        return ""
    s = html.unescape(_TAG.sub(" ", s))
    s = _WS.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] + " ..."
    return s


def arxiv_id_from(text: str | None) -> str | None:
    if not text:
        return None
    m = _ARXIV_ID.search(text)
    return m.group(1) if m else None


def arxiv_links(aid: str) -> tuple[str, str]:
    return f"https://arxiv.org/abs/{aid}", f"https://arxiv.org/pdf/{aid}"


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())
