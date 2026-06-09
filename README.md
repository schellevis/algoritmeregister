# algoritmeregister

Dit project houdt het Nederlandse Algoritmeregister (`algoritmes.overheid.nl`) als git-geschiedenis bij. Een dagelijkse GitHub Actions workflow draait `scrape.py`, schrijft de actuele stand naar `data/algoritmes.json`, commit alleen bij inhoudelijke wijzigingen en gebruikt daarmee git als changelog.

## Bron

Frequentie:

- Dagelijks via GitHub Actions cron op `06:00 UTC`

Datavorm:

- Eén JSON-bestand: `data/algoritmes.json`
- Gesorteerd op stabiele `id`
- Gestabiliseerde formatting via `json.dumps(..., sort_keys=True, indent=2, ensure_ascii=False)` plus trailing newline

Bronbevindingen van 13 mei 2026:

- De frontend gebruikt een publieke JSON-API achter `https://algoritmes.overheid.nl/api`
- Listing-endpoint: `POST https://algoritmes.overheid.nl/api/algoritme/NLD`
- Detail-endpoint: `GET https://algoritmes.overheid.nl/api/algoritme/NLD/{id}`
- De API verwacht taalcodes `NLD`, `ENG`, `FRY` en niet de URL-locale `nl`, `en`, `fy`
- Paginering gebeurt via JSON-body met `page` en `limit`
- `total_count` geeft het totaal aantal records terug; op 13 mei 2026 was dat `1431`
- Records bevatten in de listing al de velden die deze repo nodig heeft, waaronder `name`, `organization`, `goal`, `lawful_basis`, `iama`, `dpia`, `impacttoetsen`, `status`, `create_dt`, `org_id`, `lars`
- Het stabiele ID is de numerieke `lars`-waarde; als fallback kan een scraper terugvallen op `uuid`
- De frontend bundle bevat daarnaast download-URL helpers onder `/downloads/...`, maar voor deze worker is het listing-endpoint al voldoende

De scraper gebruikt daarom de publieke frontend-API en vermijdt HTML-scraping.

## Lokaal testen

Maak eerst een virtuele omgeving aan:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Daarna:

```bash
python scrape.py --dry-run
```

Voor debuggen (`--limit` werkt alleen samen met `--dry-run`, zodat een testrun nooit een onvolledige dataset wegschrijft):

```bash
python scrape.py --dry-run --limit 5
```

## Codespace / dev container

`.devcontainer/` bevat een kant-en-klare omgeving (GitHub Codespaces of lokaal via VS Code Dev Containers):

- Python 3.12 met `requirements.txt` voorgeinstalleerd
- Node LTS + `gh` CLI
- Claude Code CLI (`claude`) en Codex CLI (`codex`) globaal geinstalleerd

Open via `Code -> Codespaces -> Create codespace on main`. Authenticeer de CLI's daarna zelf (`claude` start de login-flow; `codex` gebruikt je OpenAI-key).

## Workflows

- `.github/workflows/scrape.yml`
  - draait dagelijks en via `workflow_dispatch`
  - commit en push alleen als `data/algoritmes.json` inhoudelijk wijzigt

Alle `uses:` regels zijn gepind op volledige 40-char commit-SHA's.

## Zelf draaien in een fork

1. Fork deze repo
2. Trigger de scrape handmatig via `Actions -> Scrape algoritmeregister -> Run workflow`

## GitHub Pages

De optionele viewer staat in `docs/index.html`.

Activeer Pages via:

- `Settings -> Pages`
- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/docs`

Daarna staat de viewer typisch op:

- `https://{user}.github.io/{repo}/`

## Hoe lees ik de history

Lokaal:

```bash
git log -p data/algoritmes.json
```

Online:

- `https://github.com/{repo}/commits/main/data/algoritmes.json`

## Niet inbegrepen

Bewust niet gebouwd:

- database
- eigen API
- backend-service
- multi-source aggregator
- severity-DSL

Git is de state, `data/algoritmes.json` is de dataset, en de workflows doen de rest.
