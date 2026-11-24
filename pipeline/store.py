"""SQLite store: every paper ever fetched, its embedding, and whether it has been shown."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import numpy as np

from fetchers.common import Paper, norm_title

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  key TEXT PRIMARY KEY, norm TEXT, title TEXT, abstract TEXT, url TEXT, pdf_url TEXT, code_url TEXT,
  authors TEXT, published TEXT, sources TEXT, kind TEXT, status TEXT, extra TEXT,
  first_seen TEXT, shown_on TEXT, trend_shown_on TEXT
);
CREATE INDEX IF NOT EXISTS idx_norm ON papers(norm);
CREATE INDEX IF NOT EXISTS idx_shown ON papers(shown_on);
CREATE TABLE IF NOT EXISTS embeddings (key TEXT, model TEXT, vec BLOB, PRIMARY KEY (key, model));
CREATE TABLE IF NOT EXISTS state (name TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.run_started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    # ---------- run bookkeeping ----------
    def _get(self, name: str) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def _set(self, name: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO state(name, value) VALUES (?, ?)", (name, value))

    def last_success(self, source: str) -> dt.datetime | None:
        v = self._get(f"ok:{source}")
        return dt.datetime.fromisoformat(v) if v else None

    def mark_done(self, source: str) -> None:
        self._set(f"ok:{source}", self.run_started)

    def due(self, source: str, every_days: int) -> bool:
        last = self.last_success(source)
        return last is None or dt.datetime.now(dt.timezone.utc) - last >= dt.timedelta(days=every_days)

    def file_sha(self, name: str) -> str | None:
        return self._get(f"file:{name}")

    def set_file_sha(self, name: str, sha: str) -> None:
        self._set(f"file:{name}", sha)

    def commit(self) -> None:
        self.db.commit()

    # ---------- papers ----------
    def upsert(self, p: Paper) -> bool:
        """Insert a paper, or merge it into an existing record (same key or same title).
        Returns True if the paper is new."""
        norm = norm_title(p.title)
        if not p.title or len(norm) < 8:
            return False
        row = self.db.execute("SELECT * FROM papers WHERE key=?", (p.key,)).fetchone()
        if row is None and len(norm) >= 20:
            row = self.db.execute("SELECT * FROM papers WHERE norm=? LIMIT 1", (norm,)).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO papers (key, norm, title, abstract, url, pdf_url, code_url, authors, published,"
                " sources, kind, status, extra, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.key, norm, p.title, p.abstract, p.url, p.pdf_url, p.code_url, json.dumps(p.authors),
                 p.published, json.dumps([p.source]), p.kind, p.status, json.dumps(p.extra), self.run_started))
            return True
        # merge
        sources = json.loads(row["sources"] or "[]")
        if p.source and p.source not in sources:
            sources.append(p.source)
        extra = json.loads(row["extra"] or "{}")
        extra.update({k: v for k, v in p.extra.items() if v})
        abstract = row["abstract"]
        if len(p.abstract) > len(abstract or "") + 40 and (p.kind == "paper" or row["kind"] == "blog"):
            abstract = p.abstract
            self.db.execute("DELETE FROM embeddings WHERE key=?", (row["key"],))
        # Prefer a conference status / earlier arXiv date when merging.
        self.db.execute(
            "UPDATE papers SET sources=?, extra=?, abstract=?, pdf_url=COALESCE(NULLIF(pdf_url,''), ?),"
            " code_url=COALESCE(NULLIF(code_url,''), ?), url=COALESCE(NULLIF(url,''), ?),"
            " status=COALESCE(NULLIF(status,''), ?), published=COALESCE(NULLIF(published,''), ?) WHERE key=?",
            (json.dumps(sources), json.dumps(extra), abstract, p.pdf_url, p.code_url, p.url,
             p.status, p.published, row["key"]))
        return False

    def unshown(self, blog_cutoff: str) -> list[sqlite3.Row]:
        """Candidates: never shown; blog posts only while recent (undated posts: only on the run they appear)."""
        return self.db.execute(
            "SELECT * FROM papers WHERE shown_on IS NULL AND (kind != 'blog' OR published >= ?"
            " OR (published = '' AND first_seen = ?))",
            (blog_cutoff, self.run_started)).fetchall()

    def mark_shown(self, keys: list[str], day: str) -> None:
        self.db.executemany("UPDATE papers SET shown_on=? WHERE key=?", [(day, k) for k in keys])

    def mark_trend_shown(self, keys: list[str], day: str) -> None:
        self.db.executemany("UPDATE papers SET trend_shown_on=? WHERE key=?", [(day, k) for k in keys])

    def fresh_trending(self, since: str) -> list[sqlite3.Row]:
        """Papers that came in from trending feeds during recent runs and were never listed as trending."""
        return self.db.execute(
            "SELECT * FROM papers WHERE trend_shown_on IS NULL AND first_seen >= ? AND ("
            " sources LIKE '%HF Daily%' OR sources LIKE '%alphaXiv%' OR sources LIKE '%Emergent Mind%')",
            (since,)).fetchall()

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        new = self.db.execute("SELECT COUNT(*) FROM papers WHERE first_seen=?", (self.run_started,)).fetchone()[0]
        shown = self.db.execute("SELECT COUNT(*) FROM papers WHERE shown_on IS NOT NULL").fetchone()[0]
        return {"total": total, "new": new, "shown": shown}

    # ---------- embeddings ----------
    def missing_embeddings(self, keys: list[str], model: str) -> list[str]:
        have = {r[0] for r in self.db.execute("SELECT key FROM embeddings WHERE model=?", (model,))}
        return [k for k in keys if k not in have]

    def save_embeddings(self, keys: list[str], vecs: np.ndarray, model: str) -> None:
        self.db.executemany("INSERT OR REPLACE INTO embeddings(key, model, vec) VALUES (?,?,?)",
                            [(k, model, v.astype(np.float16).tobytes()) for k, v in zip(keys, vecs)])

    def load_embeddings(self, keys: list[str], model: str) -> np.ndarray:
        want = set(keys)
        found = {}
        for k, blob in self.db.execute("SELECT key, vec FROM embeddings WHERE model=?", (model,)):
            if k in want:
                found[k] = np.frombuffer(blob, dtype=np.float16)
        return np.stack([found[k] for k in keys]).astype(np.float32)
