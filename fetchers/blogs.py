"""Research blogs from labs and organisations (RSS/Atom), plus EleutherAI (no feed; read the page)."""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
from bs4 import BeautifulSoup

from .common import Paper, clean_text


def _date(e) -> str:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return time.strftime("%Y-%m-%d", t)
    return ""


def _one_feed(session, name: str, url: str, cutoff: str, cap: int) -> tuple[list[Paper], str]:
    try:
        r = session.get(url, timeout=45)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        return [], f"{name}: failed ({e.__class__.__name__})"
    posts = []
    for e in feed.entries:
        published = _date(e)
        link = e.get("link") or ""
        if not link or (published and published < cutoff):
            continue
        body = e.get("summary") or ""
        if not body and e.get("content"):
            body = e["content"][0].get("value", "")
        posts.append(Paper(key=f"url:{link}", title=clean_text(e.get("title")),
                           abstract=clean_text(body, limit=1500), url=link,
                           published=published, source=f"{name} blog", kind="blog"))
    posts.sort(key=lambda p: p.published, reverse=True)
    return posts[:cap], f"{name}: {min(len(posts), cap)}"


def _eleutherai(session, cutoff: str) -> tuple[list[Paper], str]:
    base = "https://blog.eleuther.ai"
    try:
        r = session.get(base + "/", timeout=45)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return [], f"EleutherAI: failed ({e.__class__.__name__})"
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for card in soup.select("article.blog-card"):
        a, h = card.find("a", href=True), card.find(["h2", "h3"])
        if not a or not h:
            continue
        meta = card.select_one(".item-meta")
        published = ""
        if meta:
            try:
                published = dt.datetime.strptime(meta.get_text(strip=True), "%b %d, %Y").date().isoformat()
            except ValueError:
                pass
        if published and published < cutoff:
            continue
        paras = [p.get_text(" ", strip=True) for p in card.find_all("p") if "item-meta" not in (p.get("class") or [])]
        link = a["href"] if a["href"].startswith("http") else base + a["href"]
        posts.append(Paper(key=f"url:{link}", title=clean_text(h.get_text()), abstract=clean_text(" ".join(paras)),
                           url=link, published=published, source="EleutherAI blog", kind="blog"))
    return posts, f"EleutherAI: {len(posts)}"


def fetch(session, cfg: dict, store) -> tuple[list[Paper], list[str]]:
    cutoff = (dt.date.today() - dt.timedelta(days=int(cfg.get("max_age_days", 30)))).isoformat()
    feeds = dict(cfg.get("rss", {}))
    papers, notes = [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        cap = int(cfg.get("max_per_feed", 15))
        jobs = [ex.submit(_one_feed, session, n, u, cutoff, cap) for n, u in feeds.items()]
        if cfg.get("eleutherai", True):
            jobs.append(ex.submit(_eleutherai, session, cutoff))
        for j in jobs:
            got, note = j.result()
            papers.extend(got)
            notes.append(note)
    store.mark_done("blogs")
    return papers, ["blogs: " + ", ".join(notes)]
