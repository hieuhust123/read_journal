"""Community-curated / trending paper feeds: Hugging Face Daily Papers, Emergent Mind, alphaXiv."""
from __future__ import annotations

import datetime as dt
import json
import re

import feedparser

from .common import Paper, arxiv_id_from, arxiv_links, clean_text


def _arxiv_paper(aid: str, title: str, abstract: str, source: str, published: str = "", **extra) -> Paper:
    abs_url, pdf_url = arxiv_links(aid)
    return Paper(key=f"arxiv:{aid}", title=clean_text(title), abstract=clean_text(abstract),
                 url=abs_url, pdf_url=pdf_url, published=published[:10], source=source,
                 code_url=extra.pop("code_url", "") or "", extra={k: v for k, v in extra.items() if v})


def fetch_hf_daily(session, cfg: dict, store) -> tuple[list[Paper], list[str]]:
    last = store.last_success("hf_daily")
    today = dt.date.today()
    days = 2 if last else int(cfg.get("first_run_days", 7))
    if last:
        days = max(2, min(14, (today - last.date()).days + 1))
    papers = []
    for i in range(days):
        day = today - dt.timedelta(days=i)
        r = session.get("https://huggingface.co/api/daily_papers", params={"date": day.isoformat()}, timeout=60)
        if r.status_code != 200:
            continue
        for item in r.json():
            p = item.get("paper", {})
            aid = p.get("id")
            if not aid or not arxiv_id_from(aid):
                continue
            papers.append(_arxiv_paper(
                aid, p.get("title", ""), p.get("summary", ""), "HF Daily",
                published=p.get("publishedAt", ""), code_url=p.get("githubRepo") or "",
                upvotes=int(p.get("upvotes") or 0), hf_summary=p.get("ai_summary", ""),
            ))
    store.mark_done("hf_daily")
    return papers, [f"HF Daily Papers ({days} days): {len(papers)}"]


def fetch_emergent_mind(session, cfg: dict, store) -> tuple[list[Paper], list[str]]:
    r = session.get(cfg.get("url", "https://www.emergentmind.com/feeds/rss"), timeout=60)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    papers = []
    for rank, e in enumerate(feed.entries, 1):
        aid = arxiv_id_from(e.get("link")) or arxiv_id_from(e.get("id")) or arxiv_id_from(e.get("summary"))
        summary = clean_text(e.get("summary"))
        summary = re.sub(r"^Abstract:\s*", "", summary)
        if aid:
            papers.append(_arxiv_paper(aid, e.get("title", ""), summary, "Emergent Mind",
                                       published=dt.date.today().isoformat(), em_rank=rank))
    store.mark_done("emergent_mind")
    return papers, [f"Emergent Mind trending: {len(papers)}"]


def fetch_alphaxiv(session, cfg: dict, store) -> tuple[list[Paper], list[str]]:
    """alphaXiv has no public API; its home page embeds the trending list as schema.org JSON-LD."""
    r = session.get("https://www.alphaxiv.org/", timeout=60)
    r.raise_for_status()
    def item_lists(node):
        """Yield every schema.org itemListElement array, wherever it is nested (e.g. under @graph)."""
        if isinstance(node, dict):
            if isinstance(node.get("itemListElement"), list):
                yield node["itemListElement"]
            for v in node.values():
                yield from item_lists(v)
        elif isinstance(node, list):
            for v in node:
                yield from item_lists(v)

    papers = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', r.text, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for elements in item_lists(data):
            for el in elements:
                item = el.get("item", {}) if isinstance(el, dict) else {}
                aid = arxiv_id_from(item.get("url"))
                if not aid:
                    continue
                likes = 0
                stats = item.get("interactionStatistic") or []
                for stat in stats if isinstance(stats, list) else [stats]:
                    likes = max(likes, int(stat.get("userInteractionCount") or 0))
                papers.append(_arxiv_paper(aid, item.get("headline", ""), item.get("description", ""),
                                           "alphaXiv", published=item.get("datePublished", ""),
                                           likes=likes))
    store.mark_done("alphaxiv")
    return papers, [f"alphaXiv trending: {len(papers)}"]
