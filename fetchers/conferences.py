"""Accepted papers from NeurIPS / ICML / ICLR / AAAI.

OpenReview and the AAAI site now block scripted access, so this reads the community-maintained
mirror github.com/papercopilot/paperlists (JSON with abstracts). AAAI years missing from the
mirror are filled from OpenAlex.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import tempfile

from .common import Paper, clean_text, log

GH_API = "https://api.github.com/repos/papercopilot/paperlists/contents/{folder}"
RAW = "https://raw.githubusercontent.com/papercopilot/paperlists/main/{path}"
LFS = "https://media.githubusercontent.com/media/papercopilot/paperlists/main/{path}"

VENUE_NAMES = {"nips": "NeurIPS", "icml": "ICML", "iclr": "ICLR", "aaai": "AAAI",
               "cvpr": "CVPR", "iccv": "ICCV", "eccv": "ECCV", "colm": "COLM", "corl": "CoRL"}
ACCEPT = re.compile(r"oral|spotlight|poster|accept|technical|highlight", re.I)
REJECT = re.compile(r"reject|withdraw|desk", re.I)

OPENALEX_SOURCES = {"aaai": "S4210191458"}  # Proceedings of the AAAI Conference on AI


def _download_json(session, path: str):
    """Download a mirror file, following Git LFS pointers. Streams to disk to limit memory."""
    url = RAW.format(path=path)
    for attempt in range(2):
        with session.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with tempfile.TemporaryFile() as tmp:
                for chunk in r.iter_content(1 << 20):
                    tmp.write(chunk)
                tmp.seek(0)
                head = tmp.read(64)
                if head.startswith(b"version https://git-lfs") and attempt == 0:
                    url = LFS.format(path=path)
                    continue
                tmp.seek(0)
                return json.load(tmp)
    raise RuntimeError(f"could not download {path}")


def _from_mirror(rec: dict, venue: str, year: int, include_workshops: bool) -> Paper | None:
    title = clean_text(rec.get("title"))
    status = rec.get("status") or ""
    track = (rec.get("track") or "").lower()
    if not title or REJECT.search(status) or not ACCEPT.search(status):
        return None
    if not include_workshops and track.startswith("workshop"):
        return None
    site = rec.get("site") or ""
    rid = rec.get("id") or ""
    if "openreview.net" in site:
        key, pdf = f"or:{rid}", f"https://openreview.net/pdf?id={rid}"
    else:
        key, pdf = f"{venue}:{rid or title[:80]}", rec.get("pdf") or ""
    authors = [a.strip() for a in re.split(r"[;]", rec.get("author") or "") if a.strip()]
    kw = rec.get("keywords") or ""
    return Paper(
        key=key, title=title, abstract=clean_text(rec.get("abstract")), url=site, pdf_url=pdf,
        code_url=rec.get("github") or "", authors=authors[:12], published=str(year),
        source=f"{VENUE_NAMES.get(venue, venue.upper())} {year}", status=status if status != "Technical" else "",
        extra={"keywords": kw} if kw else {},
    )


def _openalex_year(session, venue: str, year: int, store, tag: str, api_key: str = "") -> tuple[list[Paper], bool, str]:
    """Page through OpenAlex. Without an API key the free daily budget can run out mid-way, so the
    cursor is saved and the next run resumes. Returns (papers, finished, message)."""
    src = OPENALEX_SOURCES[venue]
    papers = []
    cursor = store.file_sha(f"{tag}:cursor") or "*"
    while cursor:
        params = {"filter": f"primary_location.source.id:{src},publication_year:{year}",
                  "per-page": 200, "cursor": cursor,
                  "select": "id,title,doi,abstract_inverted_index,authorships,primary_location"}
        if api_key:
            params["api_key"] = api_key
        try:
            r = session.get("https://api.openalex.org/works", params=params, timeout=60)
            if r.status_code == 400 and cursor != "*":   # stale cursor: start over (dedup handles repeats)
                cursor = "*"
                continue
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001  (budget exhausted / rate limited)
            store.set_file_sha(f"{tag}:cursor", cursor)
            hint = "" if api_key else " (free OpenAlex key in config.yaml lifts this)"
            return papers, False, f"paused after {len(papers)} papers, resumes next run: {e.__class__.__name__}{hint}"
        data = r.json()
        for w in data.get("results", []):
            title = clean_text(w.get("title"))
            if not title:
                continue
            inv = w.get("abstract_inverted_index") or {}
            words = sorted(((pos, word) for word, poss in inv.items() for pos in poss))
            loc = w.get("primary_location") or {}
            papers.append(Paper(
                key=f"openalex:{w['id'].rsplit('/', 1)[-1]}", title=title,
                abstract=" ".join(wd for _, wd in words),
                url=loc.get("landing_page_url") or w.get("doi") or "", pdf_url=loc.get("pdf_url") or "",
                authors=[a["author"]["display_name"] for a in (w.get("authorships") or [])[:12]],
                published=str(year), source=f"{VENUE_NAMES.get(venue, venue.upper())} {year}",
            ))
        cursor = data.get("meta", {}).get("next_cursor")
        store.set_file_sha(f"{tag}:cursor", cursor or "")
        if not data.get("results"):
            break
    return papers, True, f"{len(papers)} papers"


def fetch(session, cfg: dict, store, force: bool = False) -> tuple[list[Paper], list[str]]:
    """Return (papers, notes). Only downloads files whose content changed since the last run."""
    papers: list[Paper] = []
    notes: list[str] = []
    failed = False
    this_year = dt.date.today().year
    min_year = this_year - int(cfg.get("years_back", 3)) + 1
    check_days = int(cfg.get("check_every_days", 7))
    if not force and not store.due("conferences", check_days):
        return papers, [f"conference lists checked within the last {check_days} days; skipped"]

    for venue in cfg.get("venues", []):
        try:
            r = session.get(GH_API.format(folder=venue), timeout=60)
            r.raise_for_status()
            files = r.json()
        except Exception as e:  # noqa: BLE001
            notes.append(f"{venue}: could not list mirror files ({e})")
            failed = True
            continue
        have_years = set()
        for f in files:
            m = re.fullmatch(rf"{venue}(\d{{4}})\.json", f.get("name", ""))
            # Future editions (e.g. ICLR 2027 in late 2026) are still under review: nothing accepted
            # yet, and the file changes daily as reviews arrive. Pick them up once the year comes.
            if not m or not (min_year <= int(m.group(1)) <= this_year):
                continue
            year = int(m.group(1))
            have_years.add(year)
            name = f"{venue}{year}"
            if store.file_sha(name) == f.get("sha"):
                continue
            log.info("  downloading %s.json (%.0f MB)...", name, (f.get("size") or 0) / 1e6)
            try:
                data = _download_json(session, f"{venue}/{f['name']}")
            except Exception as e:  # noqa: BLE001
                notes.append(f"{name}: download failed ({e})")
                failed = True
                continue
            got = [p for p in (_from_mirror(rec, venue, year, cfg.get("include_workshops", False))
                               for rec in data) if p]
            del data
            papers.extend(got)
            store.set_file_sha(name, f.get("sha"))
            notes.append(f"{name}: {len(got)} accepted papers")
        # Fill years missing from the mirror via OpenAlex (published proceedings only).
        if venue in OPENALEX_SOURCES:
            for year in range(min_year, this_year + 1):
                tag = f"{venue}{year}@openalex"
                if year in have_years or store.file_sha(tag) == "done":
                    continue
                got, finished, msg = _openalex_year(session, venue, year, store, tag,
                                                    cfg.get("openalex_api_key", ""))
                papers.extend(got)
                notes.append(f"{tag}: {msg}")
                if finished and got:
                    store.set_file_sha(tag, "done")
                elif not finished:
                    failed = True  # keep checking on each run until complete
    if not failed:
        store.mark_done("conferences")
    return papers, notes
