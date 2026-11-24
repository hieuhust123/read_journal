# read_journal

A daily research digest. It collects new papers and posts from conferences, arXiv, community
feeds and lab blogs, ranks them against my research profile in [config.yaml](config.yaml), and
asks Claude to explain the most promising ones: the core idea, why it matters for my work, and
one concrete thing to try.

## What it reads

| Source | How |
|---|---|
| NeurIPS, ICML, ICLR, AAAI (last 3 years, accepted papers) | [papercopilot/paperlists](https://github.com/papercopilot/paperlists) mirror (OpenReview and the AAAI site block scripts); AAAI years missing there come from OpenAlex |
| arXiv: cs.NE, cs.LG, q-bio.NC, eess.SP | arXiv API with a date window since the last run (RSS fallback) |
| Hugging Face Daily Papers, Emergent Mind, alphaXiv | their APIs / feeds |
| Lab blogs: DeepMind, Google Research, BAIR, MSR, Apple, NVIDIA, Ai2, Sakana, HF, OpenAI, EleutherAI, ... | RSS (EleutherAI: blog page) |

## How it picks papers

1. Every paper is embedded once with a local model (`BAAI/bge-base-en-v1.5`, on the GPU when available).
2. Each unseen paper is scored against the topic queries in `config.yaml` (best match wins), plus a
   small bonus for keywords and a penalty for the `avoid` themes.
3. The top new papers and the top conference/earlier papers (12 + 12) go to Claude through the local
   Claude Code CLI (your own login, no API key, all tools disabled). Claude rates each one from 1 to 5 and writes notes for the best 10.
4. Everything shown is remembered in `data/journal.db`, so it never appears again.

## Output

`digests/YYYY-MM-DD.md` and `digests/YYYY-MM-DD.html`, plus `digests/latest.html` and
`digests/index.html`. Sections: top picks with notes, other relevant papers (new / conferences),
lab posts, and community-trending papers on any topic.

## Setup (Windows)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python read_journal.py --open        # first run: downloads ~400 MB of conference lists
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1   # daily at 08:00
```

The first run builds the back catalogue (about 55k papers, a few minutes on a GPU). Later runs
only fetch what is new.

### Daily task

`scripts\install_task.ps1` registers a Task Scheduler task (`ReadJournalDigest`) that runs
`read_journal.py --open` every day and opens the finished digest in your default browser, usually
a few minutes after it starts. Details:

- It runs only while you are logged in, because Claude uses your Claude Code login. If the PC was
  off or asleep at the scheduled time, it runs soon after you log in.
- It stops after 4 hours. Downloads and embeddings are saved as it goes, so a stopped run loses only
  that day's page; the next run catches up.
- Pick another time with `-At 07:30`. Re-run the script after editing it (for example, to drop
  `--open` if you prefer to open `digests\latest.html` yourself).

## Everyday use

```powershell
.venv\Scripts\python read_journal.py --open                        # run now and open the digest
.venv\Scripts\python read_journal.py --no-fetch --no-notes --dry-run   # re-rank after editing config.yaml
.venv\Scripts\python read_journal.py --only arxiv,blogs             # fetch a subset of sources
.venv\Scripts\python read_journal.py --refresh-conferences          # check conference lists now
```

To tune what you see, edit `profile` in `config.yaml`: the `summary` is what Claude reads, the
`topics` queries drive the ranking, and `avoid` pushes unwanted themes down. Use `--dry-run` to
preview changes without marking papers as seen; previews go to `digests/preview.html` and never
overwrite a real digest. Add `--open` to see the preview straight away.

Embedding runs in fp32: on GTX 16xx laptop GPUs, fp16 is several times slower (no tensor cores).

Logs are in `logs/`, one file per day; each run starts with a line showing its options and how long
startup took. Remove the daily task with `scripts\install_task.ps1 -Remove`.
