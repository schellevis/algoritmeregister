"""Haal de volledige detail-records van het Algoritmeregister op.

Draait LOKAAL (niet in de GitHub Action). Leest de id's uit het door de Action
bijgewerkte `data/algoritmes.json` (of, met --from-listing, live uit de API) en
schrijft per algoritme een los JSON-bestand naar `detail/<id>.json`.

De bestandsnaam (`<id>`) is de `lars`-waarde en is gelijk aan het `id` in
`data/algoritmes.json`, zodat beide datasets later 1-op-1 te koppelen zijn.

Het opgeslagen record is het volledige API-detail, inclusief de velden achter de
frontend-tabjes:
  - Werking:            description, methods_and_models, source_data, monitoring,
                        human_intervention, performance_standard, provider
  - Verantwoord gebruik: lawful_basis, dpia(+_description), iama(+_description),
                        impacttoetsen, proportionality, risks, objection_procedure,
                        decision_making_process, impact, competent_authority
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://algoritmes.overheid.nl"
DETAIL_PATH = "/api/algoritme/NLD/{id}"
LIST_PATH = "/api/algoritme/NLD"
DATA_PATH = Path("data/algoritmes.json")
OUT_DIR = Path("detail")
BACKOFF_SECONDS = (1, 4, 16)
REQUEST_PAUSE = 0.15  # vriendelijk voor de bron


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape detailpagina's van het Algoritmeregister.")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="Uitvoermap (default: detail/).")
    parser.add_argument("--limit", type=int, default=None, help="Beperk het aantal id's.")
    parser.add_argument("--force", action="store_true", help="Herhaal ook al opgehaalde id's.")
    parser.add_argument(
        "--from-listing",
        action="store_true",
        help="Haal de id-lijst live uit de API in plaats van uit data/algoritmes.json.",
    )
    return parser.parse_args()


def request_json(client: httpx.Client, method: str, path: str, *, json_body: Any = None) -> Any | None:
    for attempt, backoff in enumerate(BACKOFF_SECONDS, start=1):
        try:
            response = client.request(method, path, json=json_body)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                logging.warning("HTTP %s voor %s; wacht %ss", response.status_code, path, backoff)
                time.sleep(backoff)
                continue
            if response.status_code == 404:
                logging.warning("404 voor %s; overslaan", path)
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logging.warning("Netwerkfout bij %s (poging %s/3): %s", path, attempt, exc)
            time.sleep(backoff)
    logging.error("Mislukt na retries voor %s", path)
    return None


def ids_from_file() -> list[str]:
    if not DATA_PATH.exists():
        raise SystemExit(f"{DATA_PATH} bestaat niet; gebruik --from-listing of draai eerst scrape.py.")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return [a["id"] for a in data.get("algoritmes", []) if a.get("id")]


def ids_from_listing(client: httpx.Client) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        payload = request_json(client, "POST", LIST_PATH, json_body={"page": str(page), "limit": "100"})
        if not isinstance(payload, dict):
            break
        results = payload.get("results") or []
        if not results:
            break
        ids.extend(str(r["lars"]) for r in results if r.get("lars"))
        total = payload.get("total_count", 0)
        if len(ids) >= total or len(results) < 100:
            break
        page += 1
    return ids


def fetch_detail(client: httpx.Client, algoritme_id: str) -> dict[str, Any] | None:
    payload = request_json(client, "GET", DETAIL_PATH.format(id=algoritme_id))
    if not isinstance(payload, dict):
        return None
    return {
        "id": algoritme_id,
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_url": f"{BASE_URL}{DETAIL_PATH.format(id=algoritme_id)}",
        "detail": payload,
    }


def write_detail(out_dir: Path, record: dict[str, Any]) -> None:
    path = out_dir / f"{record['id']}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    configure_logging()
    args = parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "algoritmeregister-detail-scraper/1.0"},
    ) as client:
        ids = ids_from_listing(client) if args.from_listing else ids_from_file()
        if args.limit is not None:
            ids = ids[: args.limit]
        logging.info("%s id's te verwerken naar %s/", len(ids), out_dir)

        ok = skipped = failed = 0
        for index, algoritme_id in enumerate(ids, start=1):
            target = out_dir / f"{algoritme_id}.json"
            if target.exists() and not args.force:
                skipped += 1
                continue
            record = fetch_detail(client, algoritme_id)
            if record is None:
                failed += 1
            else:
                write_detail(out_dir, record)
                ok += 1
                logging.info("[%s/%s] %s", index, len(ids), record["detail"].get("name", algoritme_id))
            time.sleep(REQUEST_PAUSE)

    logging.info("Klaar: %s opgehaald, %s overgeslagen (bestond al), %s mislukt.", ok, skipped, failed)
    return 1 if failed and ok == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
