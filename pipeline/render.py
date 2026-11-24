"""Write the digest as Markdown and as a self-contained HTML page."""
from __future__ import annotations

import datetime as dt
import html
import re
from pathlib import Path

STARS = {5: "★★★★★", 4: "★★★★☆", 3: "★★★☆☆", 2: "★★☆☆☆", 1: "★☆☆☆☆"}


def _safe_url(u: str) -> str:
    return u if re.match(r"^https?://", u or "") else ""


def _src(c) -> str:
    s = " + ".join(c.sources)
    return s + (f" · {c.status}" if c.status else "")


def _popularity(c) -> str:
    bits = []
    if c.extra.get("upvotes"):
        bits.append(f"{c.extra['upvotes']}▲ HF")
    if c.extra.get("likes"):
        bits.append(f"{c.extra['likes']}♥ alphaXiv")
    return " · ".join(bits)


def _md_escape(s: str) -> str:
    return re.sub(r"([\[\]|*_`<>])", r"\\\1", s or "")


# ------------------------------------------------------------------ Markdown
def to_markdown(d: dict) -> str:
    date = dt.date.fromisoformat(d["date"])
    st = d["stats"]
    out = [f"# Research digest · {date:%A %d %B %Y}", "",
           f"Scanned **{st['total']:,}** papers and posts (**{st['new']:,}** new this run) · "
           f"{d['claude_status']}", ""]
    if d.get("dry_run"):
        out += ["> Preview run (`--dry-run`): nothing was marked as seen.", ""]

    out += ["## Top picks", ""]
    if not d["picks"]:
        out += ["_Nothing new cleared the bar today._", ""]
    for i, c in enumerate(d["picks"], 1):
        link = _safe_url(c.url) or _safe_url(c.pdf_url)
        out.append(f"### {i}. [{_md_escape(c.title)}]({link})" if link else f"### {i}. {_md_escape(c.title)}")
        meta = [f"`{_src(c)}`", c.topic_label, f"match {c.score:.2f}"]
        if c.rating:
            meta.append(f"Claude {STARS.get(c.rating, c.rating)}")
        if c.note and c.note.get("effort"):
            meta.append(f"effort: {c.note['effort']}")
        if c.fresh:
            meta.append("**new**")
        pop = _popularity(c)
        if pop:
            meta.append(pop)
        out += [" · ".join(meta), ""]
        if c.note:
            out += [f"- **Idea:** {c.note['idea']}", f"- **Why for you:** {c.note['why']}",
                    f"- **Try:** {c.note['try']}", ""]
        links = [f"[{n}]({u})" for n, u in (("page", _safe_url(c.url)), ("pdf", _safe_url(c.pdf_url)),
                                              ("code", _safe_url(c.code_url))) if u]
        if links:
            out += [" · ".join(links), ""]
        if c.abstract:
            out += ["<details><summary>Abstract</summary>", "", c.abstract, "", "</details>", ""]

    def bullet(c, show_date=False):
        link = _safe_url(c.url) or _safe_url(c.pdf_url)
        title = f"[{_md_escape(c.title)}]({link})" if link else _md_escape(c.title)
        bits = [_src(c)]
        if show_date and c.published:
            bits.append(c.published[:10])
        bits += [c.topic_label, f"{c.score:.2f}"]
        pop = _popularity(c)
        if pop:
            bits.append(pop)
        line = f"- {title} — " + " · ".join(bits)
        if c.rating:
            line += f"  \n  _Claude {c.rating}/5: {c.reason}_"
        return line

    for title, key in (("Also relevant: new", "also_new"), ("Also relevant: conferences & earlier", "also_archive")):
        if d[key]:
            out += [f"## {title}", ""] + [bullet(c) for c in d[key]] + [""]
    if d["labs"]:
        out += ["## From the labs", ""] + [bullet(c, show_date=True) for c in d["labs"]] + [""]
    if d["trending"]:
        out += ["## Trending in the community (any topic)", ""] + [bullet(c) for c in d["trending"]] + [""]
    out += ["## Run details", ""] + [f"- {n}" for n in d["log"]] + [""]
    return "\n".join(out)


# ------------------------------------------------------------------ HTML
CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--accent:#2f5bd3;
--chip:#eef1fb;--good:#1f7a4d;--warn:#9a6400;--star:#c98a00}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1d1d21;--text:#ececef;--muted:#9b9ba3;
--line:#2e2e34;--accent:#8aa8ff;--chip:#262a3a;--good:#5fd39a;--warn:#f0b54d;--star:#f0c14d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);margin:0 0 16px}.sub a{color:var(--accent)}
.controls{position:sticky;top:0;z-index:2;background:var(--bg);padding:10px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center;border-bottom:1px solid var(--line)}
.controls input{flex:1 1 220px;min-width:0;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);font:inherit}
.chip{border:1px solid var(--line);background:var(--card);color:var(--text);border-radius:999px;padding:4px 11px;font:inherit;font-size:.85rem;cursor:pointer}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:0 0 14px}
.card h3{margin:0 0 6px;font-size:1.05rem;line-height:1.35}.card h3 a{color:var(--text);text-decoration:none}.card h3 a:hover{color:var(--accent)}
.meta{display:flex;flex-wrap:wrap;gap:6px 10px;color:var(--muted);font-size:.84rem;margin-bottom:10px}
.tag{background:var(--chip);border-radius:6px;padding:1px 7px;color:var(--text)}
.new{color:var(--good);font-weight:600}.stars{color:var(--star);letter-spacing:1px}
.note{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:8px 0}
.note b{color:var(--muted);font-weight:600;font-size:.85rem;padding-top:1px}
.links a{color:var(--accent);margin-right:14px;font-size:.9rem}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted);font-size:.88rem}
details p{margin:8px 0 0;color:var(--text);font-size:.92rem}
ul.list{list-style:none;padding:0;margin:0}ul.list li{padding:10px 0;border-bottom:1px solid var(--line)}
ul.list a{color:var(--text);text-decoration:none;font-weight:500}ul.list a:hover{color:var(--accent)}
.small{font-size:.84rem;color:var(--muted)}.why{font-style:italic}
.log{font-size:.84rem;color:var(--muted)}.warn{color:var(--warn)}
.hidden{display:none!important}
"""

JS = """
const q=document.getElementById('q');const chips=[...document.querySelectorAll('.chip')];
let topic='all';
function apply(){const t=q.value.toLowerCase();
 document.querySelectorAll('[data-topic]').forEach(el=>{
  const okT=topic==='all'||el.dataset.topic===topic||(topic==='new'&&el.dataset.fresh==='1');
  const okQ=!t||el.textContent.toLowerCase().includes(t);el.classList.toggle('hidden',!(okT&&okQ));});}
chips.forEach(c=>c.addEventListener('click',()=>{chips.forEach(x=>x.classList.remove('on'));c.classList.add('on');topic=c.dataset.t;apply();}));
q.addEventListener('input',apply);
"""


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _card(i: int, c) -> str:
    link = _safe_url(c.url) or _safe_url(c.pdf_url)
    title = f'<a href="{_e(link)}" target="_blank" rel="noopener">{_e(c.title)}</a>' if link else _e(c.title)
    meta = [f'<span class="tag">{_e(_src(c))}</span>', f"<span>{_e(c.topic_label)}</span>",
            f"<span>match {c.score:.2f}</span>"]
    if c.rating:
        meta.append(f'<span class="stars" title="Claude rating {c.rating}/5">{STARS.get(c.rating, "")}</span>')
    if c.note and c.note.get("effort"):
        meta.append(f"<span>effort: {_e(c.note['effort'])}</span>")
    if c.fresh:
        meta.append('<span class="new">new</span>')
    pop = _popularity(c)
    if pop:
        meta.append(f"<span>{_e(pop)}</span>")
    note = ""
    if c.note:
        note = ('<div class="note">' + f"<b>Idea</b><span>{_e(c.note['idea'])}</span>"
                f"<b>Why for you</b><span>{_e(c.note['why'])}</span>"
                f"<b>Try</b><span>{_e(c.note['try'])}</span></div>")
    links = "".join(f'<a href="{_e(u)}" target="_blank" rel="noopener">{n}</a>'
                    for n, u in (("page", _safe_url(c.url)), ("pdf", _safe_url(c.pdf_url)),
                                 ("code", _safe_url(c.code_url))) if u)
    abstract = f"<details><summary>Abstract</summary><p>{_e(c.abstract)}</p></details>" if c.abstract else ""
    return (f'<article class="card" data-topic="{_e(c.topic)}" data-fresh="{int(c.fresh)}">'
            f"<h3>{i}. {title}</h3><div class=\"meta\">{''.join(meta)}</div>{note}"
            f'<div class="links">{links}</div>{abstract}</article>')


def _li(c, show_date=False) -> str:
    link = _safe_url(c.url) or _safe_url(c.pdf_url)
    title = f'<a href="{_e(link)}" target="_blank" rel="noopener">{_e(c.title)}</a>' if link else _e(c.title)
    bits = [_src(c)] + ([c.published[:10]] if show_date and c.published else []) + [c.topic_label, f"{c.score:.2f}"]
    pop = _popularity(c)
    if pop:
        bits.append(pop)
    new = ' <span class="new">new</span>' if c.fresh and not show_date else ""
    why = f'<div class="small why">Claude {c.rating}/5: {_e(c.reason)}</div>' if c.rating else ""
    abstract = (f"<details><summary>Abstract</summary><p>{_e(c.abstract)}</p></details>" if c.abstract else "")
    return (f'<li data-topic="{_e(c.topic)}" data-fresh="{int(c.fresh)}">{title}{new}'
            f'<div class="small">{_e(" · ".join(bits))}</div>{why}{abstract}</li>')


def to_html(d: dict, topics: dict, history: list[str]) -> str:
    date = dt.date.fromisoformat(d["date"])
    st = d["stats"]
    chips = ['<button class="chip on" data-t="all">All</button>', '<button class="chip" data-t="new">New only</button>']
    chips += [f'<button class="chip" data-t="{_e(t)}">{_e(lbl)}</button>' for t, lbl in topics.items()]
    body = [f"<h1>Research digest</h1>",
            f'<p class="sub">{date:%A %d %B %Y} · scanned {st["total"]:,} papers and posts '
            f'({st["new"]:,} new) · {_e(d["claude_status"])} · <a href="index.html">all digests</a></p>']
    if d.get("dry_run"):
        body.append('<p class="sub warn">Preview run (--dry-run): nothing was marked as seen.</p>')
    body.append(f'<div class="controls"><input id="q" type="search" placeholder="Filter by word...">{"".join(chips)}</div>')
    body.append("<h2>Top picks</h2>")
    body += [_card(i, c) for i, c in enumerate(d["picks"], 1)] or ['<p class="sub">Nothing new cleared the bar today.</p>']
    for title, key, show_date in (("Also relevant: new", "also_new", False),
                                  ("Also relevant: conferences &amp; earlier", "also_archive", False),
                                  ("From the labs", "labs", True),
                                  ("Trending in the community (any topic)", "trending", False)):
        if d[key]:
            body.append(f"<h2>{title}</h2><ul class=\"list\">" + "".join(_li(c, show_date) for c in d[key]) + "</ul>")
    body.append('<h2>Run details</h2><ul class="log">' + "".join(f"<li>{_e(n)}</li>" for n in d["log"]) + "</ul>")
    if history:
        body.append('<p class="small">Earlier: ' + " · ".join(
            f'<a href="{_e(h)}.html">{_e(h)}</a>' for h in history[:14]) + "</p>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Research digest {d['date']}</title><style>{CSS}</style></head>"
            f"<body><main>{''.join(body)}</main><script>{JS}</script></body></html>")


def index_html(dates: list[str]) -> str:
    items = "".join(f'<li><a href="{_e(x)}.html">{dt.date.fromisoformat(x):%A %d %B %Y}</a></li>' for x in dates)
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Research digests</title>"
            f"<style>{CSS}</style></head><body><main><h1>Research digests</h1>"
            f'<ul class="list">{items}</ul></main></body></html>')


def write_all(d: dict, topics: dict, out_dir: Path) -> tuple[Path, Path]:
    """Write the dated digest (or preview.* for --dry-run, leaving real digests untouched)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in out_dir.glob("*.html") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)}
    stem = "preview" if d.get("dry_run") else d["date"]
    dates = sorted(existing | ({d["date"]} if stem != "preview" else set()), reverse=True)
    md_path, html_path = out_dir / f"{stem}.md", out_dir / f"{stem}.html"
    md_path.write_text(to_markdown(d), encoding="utf-8")
    page = to_html(d, topics, [x for x in dates if x != d["date"]])
    html_path.write_text(page, encoding="utf-8")
    if stem != "preview":
        (out_dir / "latest.html").write_text(page, encoding="utf-8")
        (out_dir / "index.html").write_text(index_html(dates), encoding="utf-8")
    return md_path, html_path
