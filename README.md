# algoritmeregister

Dit project houdt het Nederlandse Algoritmeregister (`algoritmes.overheid.nl`) als git-geschiedenis bij. Een dagelijkse GitHub Actions workflow draait `scrape.py`, schrijft de actuele stand naar `data/algoritmes.json`, commit alleen bij inhoudelijke wijzigingen en gebruikt daarmee git als changelog. Een tweede workflow draait op push naar dat bestand, berekent wat er veranderde en kan relevante wijzigingen naar `ntfy` sturen via `alert.py`.

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
python alert.py --since HEAD~1 --dry-run
```

Voor debuggen:

```bash
python scrape.py --limit 5
python scrape.py --dry-run --limit 3
```

## Workflows

- `.github/workflows/scrape.yml`
  - draait dagelijks en via `workflow_dispatch`
  - commit en push alleen als `data/algoritmes.json` inhoudelijk wijzigt
- `.github/workflows/alert.yml`
  - draait op push naar `data/algoritmes.json` op `main`
  - leest `HEAD~1` en de nieuwe file, classificeert events en post naar `ntfy`

Alle `uses:` regels zijn gepind op volledige 40-char commit-SHA's.

## Zelf draaien in een fork

1. Fork deze repo
2. Zet `NTFY_TOPIC` in `Settings -> Secrets and variables -> Actions`
3. Optioneel: zet `NTFY_AUTH` als je topic authenticatie gebruikt
4. Trigger de scrape handmatig via `Actions -> Scrape algoritmeregister -> Run workflow`

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
