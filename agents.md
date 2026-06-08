# Agent Notes

This repository is a standalone git-scraping worker for the Dutch Algoritmeregister (`algoritmes.overheid.nl`).

## Scope

- Keep this repo simple: one scraper, one GitHub Actions workflow, one static viewer.
- Do not add a database, backend service, API layer, queue, or extra infrastructure.
- Git history is the changelog. `data/algoritmes.json` is the dataset.

## Source of Truth

- Prefer the public frontend API, not HTML scraping.
- Listing endpoint: `POST https://algoritmes.overheid.nl/api/algoritme/NLD`
- API language codes are `NLD`, `ENG`, `FRY`.
- Avoid reintroducing Nuxt payload scraping unless the API disappears.

## Scraper Rules

- Python 3.12.
- Use `httpx` sync client.
- Output must be written only to `data/algoritmes.json`.
- Keep output deterministic:
  - sort records by `id`
  - serialize with `json.dumps(..., sort_keys=True, indent=2, ensure_ascii=False)`
  - end file with a trailing newline
- Keep `fetched_at` only at top level, never per record.
- Skip rewriting the file when only `fetched_at` would change, so unchanged
  runs produce no commit (git history stays substantive).
- Stable IDs:
  - prefer `lars` (the register's numeric record id, used in public URLs)
  - otherwise fall back to `uuid`
  - never use timestamps or content hashes in IDs

## Failure Handling

- On 429: respect `Retry-After` if present.
- Retries/backoff: `1s`, `4s`, `16s`.
- On 5xx: retry with backoff.
- On 4xx, parse error, or empty response: exit non-zero and do not overwrite `data/algoritmes.json`.

## Local Validation

Run these before finishing changes:

```bash
python scrape.py --dry-run
python -m py_compile scrape.py
```

If you touch workflows, also verify:

```bash
grep -nE "uses:.*@(v[0-9]|main|master)" .github/workflows/*.yml
```

Expected result: no matches.
