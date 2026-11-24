"""Daily research digest: fetch new papers, rank them against my research profile, ask Claude for
notes on the most promising ones, and write Markdown + HTML digests.

Usage:
  python read_journal.py                  # normal daily run
  python read_journal.py --open           # ...and open the HTML digest when done
  python read_journal.py --no-fetch --no-notes --dry-run   # re-rank only, to tune config.yaml
  python read_journal.py --only arxiv,blogs                 # fetch a subset of sources
"""
from __future__ import annotations

import time

T_PROCESS = time.time()  # before the heavy imports, so slow startups show up in the log

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "hf"))          # keep model cache on this drive
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import yaml  # noqa: E402

from fetchers import arxiv_fetcher, blogs, conferences, trending  # noqa: E402
from fetchers.common import make_session  # noqa: E402
from pipeline import notes, render  # noqa: E402
from pipeline.ranker import Ranker  # noqa: E402
from pipeline.store import Store  # noqa: E402

log = logging.getLogger("journal")

SOURCES = {
    "conferences": lambda s, c, st, a: conferences.fetch(s, c, st, force=a.refresh_conferences),
    "arxiv": lambda s, c, st, a: arxiv_fetcher.fetch(s, c, st),
    "hf_daily": lambda s, c, st, a: trending.fetch_hf_daily(s, c, st),
    "emergent_mind": lambda s, c, st, a: trending.fetch_emergent_mind(s, c, st),
    "alphaxiv": lambda s, c, st, a: trending.fetch_alphaxiv(s, c, st),
    "blogs": lambda s, c, st, a: blogs.fetch(s, c, st),
}


def setup_logging() -> None:
    headless = sys.stdout is None  # pythonw (scheduled runs) has no console
    if headless:
        # Libraries (progress bars, warnings) write to these; give them somewhere harmless to go.
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    (ROOT / "logs").mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(ROOT / "logs" / f"{dt.date.today():%Y-%m-%d}.log", encoding="utf-8")]
    if not headless:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=handlers)
    for noisy in ("httpx", "httpcore", "httpx2", "httpcore2", "huggingface_hub", "sentence_transformers",
                  "transformers", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def fetch_all(args, cfg, store) -> list[str]:
    session = make_session()
    run_log = []
    wanted = set(args.only.split(",")) if args.only else set(SOURCES)
    for name, fn in SOURCES.items():
        scfg = cfg["sources"].get(name, {})
        if name not in wanted or not scfg.get("enabled", True):
            continue
        t0 = time.time()
        log.info("Fetching %s ...", name)
        try:
            papers, msgs = fn(session, scfg, store, args)
        except Exception as e:  # noqa: BLE001  (one broken source must not kill the digest)
            log.exception("  %s failed", name)
            run_log.append(f"{name}: FAILED ({e.__class__.__name__}: {e})")
            continue
        new = sum(store.upsert(p) for p in papers)
        store.commit()
        msg = f"{name}: {len(papers)} fetched, {new} new ({time.time() - t0:.0f}s)"
        log.info("  %s", msg)
        run_log.append(msg + ("; " + "; ".join(msgs) if msgs else ""))
    return run_log


def diverse_top(items, n: int, per_topic: int):
    """Best `n` items by score, after first reserving the best `per_topic` items of every topic.
    `items` must already be sorted by score (descending)."""
    chosen, taken, count = [], set(), {}
    for c in items:
        if count.get(c.topic, 0) < per_topic:
            chosen.append(c)
            taken.add(c.key)
            count[c.topic] = count.get(c.topic, 0) + 1
    for c in items:
        if len(chosen) >= n:
            break
        if c.key not in taken:
            chosen.append(c)
            taken.add(c.key)
    return sorted(chosen, key=lambda c: c.score, reverse=True)[:n]


def select(scored, cfg, reviewed_ok: bool):
    """Split scored candidates into the digest sections."""
    dg = cfg["digest"]
    per_topic = int(dg.get("min_per_topic", 1))
    picks = [c for c in scored if c.note]
    picks.sort(key=lambda c: (c.rating or 0, c.score), reverse=True)
    picks = picks[: int(dg.get("notes_top", 10))]
    if not reviewed_ok:  # no Claude: fall back to embedding order
        picks = diverse_top([c for c in scored if c.kind == "paper"], int(dg.get("notes_top", 10)), per_topic)
    used = {c.key for c in picks}

    def also(fresh: bool, n: int):
        pool = [c for c in scored if c.key not in used and c.kind == "paper" and c.fresh == fresh]
        rated = sorted((c for c in pool if c.rating and c.rating >= 3),
                       key=lambda c: (c.rating, c.score), reverse=True)
        rest = diverse_top([c for c in pool if c.rating is None], max(0, n - len(rated)), per_topic)
        out = (rated + rest)[:n]
        used.update(c.key for c in out)
        return out

    also_new = also(True, int(dg.get("also_new", 15)))
    also_archive = also(False, int(dg.get("also_archive", 15)))
    labs_min = float(dg.get("labs_min_score", 0))
    labs = [c for c in scored if c.kind == "blog" and c.key not in used
            and c.score >= labs_min][: int(dg.get("labs", 8))]
    used.update(c.key for c in labs)
    dropped = [c.key for c in scored if c.rating is not None and c.key not in used]  # Claude said <3
    return picks, also_new, also_archive, labs, dropped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--no-fetch", action="store_true", help="skip downloading; rank what is already stored")
    ap.add_argument("--no-notes", action="store_true", help="skip the Claude review step")
    ap.add_argument("--dry-run", action="store_true", help="do not mark anything as seen")
    ap.add_argument("--only", default="", help="comma-separated sources: " + ",".join(SOURCES))
    ap.add_argument("--refresh-conferences", action="store_true", help="check conference lists now")
    ap.add_argument("--open", action="store_true", help="open the HTML digest when done")
    args = ap.parse_args()

    setup_logging()
    log.info("Run started (%s; startup took %.0fs)", " ".join(sys.argv[1:]) or "no options",
             time.time() - T_PROCESS)
    cfg =yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    today = dt.date.today().isoformat()
    store = Store(ROOT / "data" / "journal.db")
    t_start = time.time()

    run_log = [] if args.no_fetch else fetch_all(args, cfg, store)

    # ---- rank
    rk = cfg.get("ranking", {})
    ranker = Ranker(rk, cfg["profile"])
    blog_cut = (dt.date.today() - dt.timedelta(days=int(cfg["sources"]["blogs"].get("max_age_days", 30)))).isoformat()
    rows = store.unshown(blog_cut)
    n_emb = ranker.embed_missing(store, rows, show_progress=bool(sys.stdout and sys.stdout.isatty()))
    if n_emb:
        run_log.append(f"embedded {n_emb} new items with {ranker.model_name}")
    scored = ranker.score(store, rows, store.run_started)
    log.info("Ranked %d unseen items", len(scored))

    # ---- Claude review of the best fresh + best archive candidates
    dg = cfg["digest"]
    per_topic = int(dg.get("min_per_topic", 1))
    fresh = diverse_top([c for c in scored if c.fresh], int(dg.get("fresh_candidates", 12)), per_topic)
    archive = diverse_top([c for c in scored if not c.fresh and c.kind == "paper"],
                          int(dg.get("archive_candidates", 12)), per_topic)
    candidates = sorted(fresh + archive, key=lambda c: c.score, reverse=True)
    reviewed, claude_status = {}, "Claude notes off"
    if candidates and cfg.get("claude", {}).get("enabled", True) and not args.no_notes:
        reviewed, claude_status = notes.review(candidates, cfg["profile"]["summary"], cfg["claude"],
                                               int(dg.get("notes_top", 10)))
        log.info(claude_status)
    for c in candidates:
        r = reviewed.get(c.key)
        if r:
            c.rating, c.reason, c.note = r["rating"], r["reason"], r.get("note")
    picks, also_new, also_archive, labs, dropped = select(scored, cfg, bool(reviewed))

    # ---- community trending (any topic), not repeated across days
    shown_now = {c.key for c in picks + also_new + also_archive + labs}
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat(timespec="seconds")
    by_key = {c.key: c for c in scored}
    trend = [by_key[r["key"]] for r in store.fresh_trending(since) if r["key"] in by_key and r["key"] not in shown_now]
    trend.sort(key=lambda c: (c.extra.get("upvotes", 0) + 3 * c.extra.get("likes", 0)
                              + (40 - 4 * c.extra.get("em_rank", 10) if c.extra.get("em_rank") else 0)), reverse=True)
    trend = trend[: int(dg.get("trending", 6))]

    if not args.dry_run:
        store.mark_shown(list(shown_now) + dropped, today)
        store.mark_trend_shown([c.key for c in trend], today)
        store.commit()

    stats = store.stats()
    run_log.append(f"pool: {stats['total']:,} items stored, {len(scored):,} unseen before this digest; "
                   f"run took {time.time() - t_start:.0f}s")
    digest = {"date": today, "picks": picks, "also_new": also_new, "also_archive": also_archive,
              "labs": labs, "trending": trend, "stats": stats, "log": run_log,
              "claude_status": claude_status, "dry_run": args.dry_run}
    topics = {t: v.get("label", t) for t, v in cfg["profile"]["topics"].items()}
    md_path, html_path = render.write_all(digest, topics, ROOT / dg.get("output_dir", "digests"))
    log.info("Digest written: %s", html_path)
    log.info("               %s", md_path)
    if args.open:
        try:
            if sys.platform == "win32":
                os.startfile(html_path)
            else:
                import webbrowser
                webbrowser.open(Path(html_path).resolve().as_uri())
        except OSError:
            log.exception("Could not open the digest in a browser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
