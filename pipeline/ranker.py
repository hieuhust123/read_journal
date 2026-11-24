"""Relevance ranking: embed papers with a local model and compare them with the research profile."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("journal")

# BGE models expect this prefix on short queries (not on the documents).
QUERY_PREFIX = {"bge": "Represent this sentence for searching relevant passages: "}


@dataclass
class Scored:
    key: str
    title: str
    abstract: str
    url: str
    pdf_url: str
    code_url: str
    authors: list
    published: str
    sources: list
    kind: str
    status: str
    extra: dict
    score: float
    topic: str
    topic_label: str
    fresh: bool
    keyword_hits: list = field(default_factory=list)
    # filled in by Claude
    rating: int | None = None
    reason: str = ""
    note: dict | None = None


def _doc_text(row) -> str:
    extra = json.loads(row["extra"] or "{}")
    kw = extra.get("keywords") or ""
    parts = [row["title"], f"Keywords: {kw}" if kw else "", row["abstract"] or ""]
    return ". ".join(p for p in parts if p)[:3000]


class Ranker:
    def __init__(self, cfg: dict, profile: dict):
        self.cfg = cfg
        self.model_name = cfg.get("model", "BAAI/bge-base-en-v1.5")
        self.profile = profile
        self._model = None

    @property
    def model(self):
        if self._model is None:
            # Once the model is cached, load it offline: no Hub calls, works without internet.
            cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
            if (cache / "hub" / f"models--{self.model_name.replace('/', '--')}" / "snapshots").exists():
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
            import torch
            from sentence_transformers import SentenceTransformer
            device = self.cfg.get("device", "auto")
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info("Loading embedding model %s on %s", self.model_name, device)
            m = SentenceTransformer(self.model_name, device=device)
            m.max_seq_length = int(self.cfg.get("max_tokens", 320))
            # fp16 is ~6x slower than fp32 on GTX 16xx cards (no tensor cores), so it is opt-in.
            if device == "cuda" and self.cfg.get("fp16", False):
                m.half()
            self._model = m
        return self._model

    def _encode(self, texts: list[str], show_progress: bool = False) -> np.ndarray:
        return self.model.encode(texts, batch_size=int(self.cfg.get("batch_size", 64)),
                                 normalize_embeddings=True, show_progress_bar=show_progress,
                                 convert_to_numpy=True)

    def embed_missing(self, store, rows, show_progress: bool) -> int:
        by_key = {r["key"]: r for r in rows}
        missing = store.missing_embeddings(list(by_key), self.model_name)
        if not missing:
            return 0
        log.info("Embedding %d papers with %s ...", len(missing), self.model_name)
        # Sort by length so batches pad less (much faster on long backlogs).
        missing.sort(key=lambda k: len(_doc_text(by_key[k])))
        chunk = 4096
        for i in range(0, len(missing), chunk):
            keys = missing[i:i + chunk]
            vecs = self._encode([_doc_text(by_key[k]) for k in keys], show_progress)
            store.save_embeddings(keys, vecs, self.model_name)
            store.commit()
        return len(missing)

    def score(self, store, rows, run_started: str) -> list[Scored]:
        if not rows:
            return []
        topics = self.profile["topics"]
        prefix = next((v for k, v in QUERY_PREFIX.items() if k in self.model_name.lower()), "")
        q_texts, q_topic = [], []
        for tid, t in topics.items():
            for q in t["queries"]:
                q_texts.append(prefix + q)
                q_topic.append(tid)
        avoid = self.profile.get("avoid", []) or []
        q_vecs = self._encode(q_texts + [prefix + a for a in avoid])
        topic_vecs, avoid_vecs = q_vecs[:len(q_texts)], q_vecs[len(q_texts):]

        keys = [r["key"] for r in rows]
        P = store.load_embeddings(keys, self.model_name)
        sims = P @ topic_vecs.T                                   # (papers, queries)
        tids = list(topics)
        per_topic = np.stack([sims[:, [i for i, t in enumerate(q_topic) if t == tid]].max(axis=1)
                              for tid in tids], axis=1)           # (papers, topics)
        best_idx = per_topic.argmax(axis=1)
        best = per_topic.max(axis=1)
        if len(avoid_vecs):
            av = (P @ avoid_vecs.T).max(axis=1)
            best_adj = best - np.clip(av - best, 0, None)
        else:
            best_adj = best

        # One combined regex (longest first) instead of one per keyword: ~50x faster on the backlog.
        kws = sorted({k for t in topics.values() for k in t.get("boost_keywords", [])}, key=len, reverse=True)
        kw_rx = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, kws)) + r")(?![\w-])", re.I) if kws else None
        kw_canon = {k.lower(): k for k in kws}
        step = float(self.cfg.get("keyword_boost", 0.02))
        cap = float(self.cfg.get("keyword_boost_max", 0.05))
        fresh_cut = (dt.date.today() - dt.timedelta(days=int(self.cfg.get("fresh_days", 14)))).isoformat()

        out = []
        for i, r in enumerate(rows):
            text = f"{r['title']} {r['abstract'] or ''}"
            hits = sorted({kw_canon.get(m.lower(), m) for m in kw_rx.findall(text)}) if kw_rx else []
            boost = min(cap, step * len(hits))
            pub = r["published"] or ""
            fresh = pub[:10] >= fresh_cut if len(pub) >= 10 else (r["first_seen"] == run_started and r["kind"] == "blog")
            tid = tids[best_idx[i]]
            out.append(Scored(
                key=r["key"], title=r["title"], abstract=r["abstract"] or "", url=r["url"] or "",
                pdf_url=r["pdf_url"] or "", code_url=r["code_url"] or "",
                authors=json.loads(r["authors"] or "[]"), published=pub,
                sources=json.loads(r["sources"] or "[]"), kind=r["kind"], status=r["status"] or "",
                extra=json.loads(r["extra"] or "{}"), score=float(best_adj[i] + boost),
                topic=tid, topic_label=topics[tid].get("label", tid), fresh=bool(fresh), keyword_hits=hits,
            ))
        out.sort(key=lambda s: s.score, reverse=True)
        return out
