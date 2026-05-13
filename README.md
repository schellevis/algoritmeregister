# algoritmeregister

Standalone git-scraper voor het Nederlandse Algoritmeregister. GitHub Actions haalt dagelijks de publieke bron op, schrijft de actuele stand naar `data/algoritmes.json`, commit alleen bij wijzigingen, en gebruikt git-history als changelog.

## Bron

De publieke frontend op `https://algoritmes.overheid.nl` gebruikt geen publiek lees-API endpoint dat direct beschikbaar was tijdens inspectie op 13 mei 2026. De site rendert de data server-side in een Nuxt `__NUXT_DATA__` payload. De publieke paden `/api` en `/aanleverapi` gaven toen een `404`; release notes op de site verwijzen wel naar een aanlever-API voor publicerende organisaties, niet naar een publieke read-API voor bezoekers.

Bevindingen uit de bron:

- Overzichtspagina: `https://algoritmes.overheid.nl/nl/algoritme?page=N`
- Paginering: ja, via `?page=N`
- Resultaten per pagina: 10
- Totaal aantal op 13 mei 2026: 1431
- Stabiele identifier: het detailpad bevat een numerieke ID, bijvoorbeeld `/nl/algoritme/89931921`; in de detailpayload staat die als `lars`
- Detailvelden in de payload bevatten onder meer `name`, `organization`, `goal`, `lawful_basis`, `iama`, `dpia`, `impacttoetsen`, `status`, `create_dt`, `org_id` en `lars`

## Lokaal testen

Maak eerst een virtuele omgeving aan en installeer dependencies:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Daarna:

```bash
./.venv/bin/python scrape.py --dry-run
./.venv/bin/python alert.py --since HEAD~1 --dry-run
```

## Zelf draaien in een fork

- Fork deze repo
- Zet `NTFY_TOPIC` als Actions secret in je repo
- Trigger de workflow handmatig via de Actions-tab

## Hoe lees ik de history

```bash
git log -p data/algoritmes.json
```

Online:

`github.com/{repo}/commits/main/data/algoritmes.json`
