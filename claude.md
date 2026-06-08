# Claude Notes

Use this repo as a small, deterministic scraper project.

## What matters

- Preserve low operational complexity.
- Prefer conservative edits over abstraction.
- Keep diffs readable because git history is the product.

## Repo-specific guidance

- The current scraper uses the public frontend API at `/api/algoritme/NLD`.
- Do not switch back to HTML scraping unless the API is gone or broken.
- `data/algoritmes.json` is regenerated output. Treat it as machine-written.
- `README.md` must document the real source path and the actual local test flow.

## Editing expectations

- Keep Python typed.
- Avoid unrelated refactors.
- Keep workflows pinned to full 40-character commit SHAs.
- Do not add dependencies without a direct need.

## Verification checklist

Before you hand work back:

1. `python scrape.py --dry-run` returns plausible records.
2. Two dry-runs produce stable IDs for the same entries.
3. Workflow `uses:` lines remain SHA-pinned.
4. README still matches the implementation.
