"""New arXiv submissions in chosen categories, using the arXiv API with a date window.

Falls back to the daily RSS announcement feed if the API misbehaves.
"""
from __future__ import annotations

import datetime as dt
import time

import feedparser

from .common import Paper, arxiv_id_from, arxiv_links, clean_text, log

API = "https://export.arxiv.org/api/query"
PAGE = 500


def _entry_to_paper(e, label: str = "arXiv") -> Paper | None:
    aid = arxiv_id_from(e.get("id") or e.get("link"))
    if not aid:
        return None
    abs_url, pdf_url = arxiv_links(aid)
    t = e.get("published_parsed") or e.get("updated_parsed")
    published = time.strftime("%Y-%m-%d", t) if t else ""
    abstract = clean_text(e.get("summary"))
    # RSS summaries start with "arXiv:XXXX Announce Type: new Abstract: ..."
    if "Abstract:" in abstract[:200]:
        abstract = abstract.split("Abstract:", 1)[1].strip()
    cats = [t.get("term") for t in e.get("tags", []) if t.get("term")]
    return Paper(
        key=f"arxiv:{aid}", title=clean_text(e.get("title")), abstract=abstract,
        url=abs_url, pdf_url=pdf_url,
        authors=[a.get("name", "") for a in e.get("authors", [])][:12],
        published=published, source=label, extra={"categories": cats[:6]} if cats else {},
    )


def _api_window(session, cats, start: dt.datetime, end: dt.datetime, cap: int) -> list[Paper]:
    cat_q = " OR ".join(f"cat:{c}" for c in cats)
    q = f"({cat_q}) AND submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"
    papers, offset = [], 0
    while offset < cap:
        params = {"search_query": q, "start": offset, "max_results": PAGE,
                  "sortBy": "submittedDate", "sortOrder": "descending"}
        r = session.get(API, params=params, timeout=120)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        batch = [p for p in (_entry_to_paper(e) for e in feed.entries) if p]
        papers.extend(batch)
        total = int(feed.feed.get("opensearch_totalresults", 0) or 0)
        log.info("  arXiv API: %d / %d", len(papers), total)
        offset += PAGE
        if len(feed.entries) < PAGE or offset >= total:
            break
        time.sleep(3)  # arXiv API etiquette
    return papers


def _rss(session, cats) -> list[Paper]:
    r = session.get("https://rss.arxiv.org/rss/" + "+".join(cats), timeout=60)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    today = dt.date.today().isoformat()
    out = []
    for e in feed.entries:
        # Keep new submissions and cross-lists; skip "replace"/"replace-cross" (revisions of old papers).
        if (e.get("arxiv_announce_type") or "new") not in ("new", "cross"):
            continue
        p = _entry_to_paper(e)
        if p:
            p.published = p.published or today
            out.append(p)
    return out


def fetch(session, cfg: dict, store) -> tuple[list[Paper], list[str]]:
    cats = cfg.get("categories", ["cs.LG"])
    last = store.last_success("arxiv")
    now = dt.datetime.now(dt.timezone.utc)
    if last:
        # The API index can lag announcements by a few days (weekends especially), so overlap
        # generously; dedup makes repeats free.
        start = min(last, now) - dt.timedelta(days=5)
    else:
        start = now - dt.timedelta(days=int(cfg.get("first_run_days", 7)))
    start = max(start, now - dt.timedelta(days=30))
    papers, notes = [], []
    try:
        api = _api_window(session, cats, start, now, int(cfg.get("max_results", 6000)))
        papers += api
        notes.append(f"API {start:%Y-%m-%d}..{now:%Y-%m-%d}: {len(api)}")
    except Exception as e:  # noqa: BLE001
        notes.append(f"API failed ({e.__class__.__name__})")
    try:  # today's announcements: always current, even when the API index lags
        rss = _rss(session, cats)
        papers += rss
        notes.append(f"RSS today: {len(rss)}")
    except Exception as e:  # noqa: BLE001
        notes.append(f"RSS failed ({e.__class__.__name__})")
    if papers:
        store.mark_done("arxiv")
    return papers, ["arXiv " + ", ".join(notes)]
