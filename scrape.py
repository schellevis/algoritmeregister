from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://algoritmes.overheid.nl"
SOURCE_URL = f"{BASE_URL}/api/algoritme/NLD"
LIST_PATH = "/api/algoritme/NLD"
DATA_PATH = Path("data/algoritmes.json")
BACKOFF_SECONDS = (1, 4, 16)
WHITESPACE_REPLACEMENTS = ("\xa0", "\t", "\r", "\n")


class ScrapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlgorithmDetail:
    id: str
    title: str
    url: str
    organisatie: str
    doel: str
    juridische_basis: str
    impactassessment: str
    status: str
    laatst_gewijzigd: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape het Algoritmeregister.")
    parser.add_argument("--dry-run", action="store_true", help="Print eerste 3 records, schrijf niets.")
    parser.add_argument("--limit", type=int, default=None, help="Beperk het aantal records.")
    return parser.parse_args()


def parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    delta = retry_at - datetime.now(retry_at.tzinfo or UTC)
    return max(0, math.ceil(delta.total_seconds()))


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, str] | None = None,
) -> Any:
    last_error: Exception | None = None

    for attempt, backoff in enumerate(BACKOFF_SECONDS, start=1):
        try:
            response = client.request(method, path, json=json_body)
            if response.status_code == 429:
                wait_seconds = parse_retry_after(response.headers.get("Retry-After")) or backoff
                logging.warning("429 ontvangen voor %s; wacht %ss", path, wait_seconds)
                time.sleep(wait_seconds)
                continue
            if 500 <= response.status_code < 600:
                logging.warning("Serverfout %s voor %s; wacht %ss", response.status_code, path, backoff)
                time.sleep(backoff)
                continue
            if 400 <= response.status_code < 500:
                raise ScrapeError(f"Clientfout {response.status_code} voor {path}")

            response.raise_for_status()
            if not response.content.strip():
                logging.warning("Lege response voor %s", path)
                raise ScrapeError(f"Lege response voor {path}")
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise ScrapeError(f"Kon JSON niet parsen voor {path}: {exc}") from exc
        except httpx.HTTPError as exc:
            last_error = exc
            logging.warning("Netwerkfout bij %s (poging %s/3): %s", path, attempt, exc)
            time.sleep(backoff)

    if last_error is not None:
        raise ScrapeError(f"Mislukt na retries voor {path}: {last_error}") from last_error
    raise ScrapeError(f"Mislukt na retries voor {path}")


def normalize_whitespace(value: str) -> str:
    text = value
    for token in WHITESPACE_REPLACEMENTS:
        text = text.replace(token, " ")
    return " ".join(text.split()).strip()


def html_fragment_to_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return normalize_whitespace(str(value))
    if "<" not in value and ">" not in value:
        return normalize_whitespace(unescape(value))
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return normalize_whitespace(unescape(text))


def normalize_status(value: Any) -> str:
    normalized = normalize_whitespace(str(value)).lower()
    mapping = {
        "in gebruik": "in_gebruik",
        "in ontwikkeling": "ontwikkeling",
        "uitgefaseerd": "uitgefaseerd",
    }
    return mapping.get(normalized, normalized.replace(" ", "_"))


def normalize_impactassessment(item: dict[str, Any]) -> str:
    candidates = [
        html_fragment_to_text(item.get("impacttoetsen")),
        html_fragment_to_text(item.get("impacttoetsen_grouping")),
        html_fragment_to_text(item.get("iama")),
        html_fragment_to_text(item.get("iama_description")),
        html_fragment_to_text(item.get("dpia")),
        html_fragment_to_text(item.get("dpia_description")),
    ]
    joined = " ".join(candidate for candidate in candidates if candidate).strip().lower()
    if not joined:
        return "Onbekend"
    if joined == "geen":
        return "Nee"
    return "Ja"


def extract_stable_id(item: dict[str, Any]) -> str:
    for key in ("lars", "uuid"):
        value = item.get(key)
        if value is not None and normalize_whitespace(str(value)):
            return normalize_whitespace(str(value))
    organisatie = normalize_whitespace(str(item.get("organization", "")))
    naam = normalize_whitespace(str(item.get("name", "")))
    if not organisatie or not naam:
        raise ScrapeError("Kon geen stabiele id afleiden")
    slug_source = f"{organisatie}-{naam}".lower()
    allowed = [character if character.isalnum() else "-" for character in slug_source]
    return "".join(allowed).strip("-")


def build_url(stable_id: str) -> str:
    # The register's frontend resolves /nl/algoritme/{lars} and redirects to the
    # canonical URL. Prefixing with org_id 404s, because the canonical org segment
    # (e.g. gm1949) differs from org_id.
    return f"{BASE_URL}/nl/algoritme/{stable_id}"


def build_detail(item: dict[str, Any]) -> AlgorithmDetail:
    stable_id = extract_stable_id(item)
    create_dt = normalize_whitespace(str(item.get("create_dt", "")))
    if not create_dt:
        raise ScrapeError(f"Algoritme {stable_id} mist create_dt")

    return AlgorithmDetail(
        id=stable_id,
        title=normalize_whitespace(str(item.get("name", ""))),
        url=build_url(stable_id),
        organisatie=normalize_whitespace(str(item.get("organization", ""))),
        doel=html_fragment_to_text(item.get("goal")),
        juridische_basis=html_fragment_to_text(item.get("lawful_basis")),
        impactassessment=normalize_impactassessment(item),
        status=normalize_status(item.get("status", "")),
        laatst_gewijzigd=create_dt[:10],
    )


def fetch_listing_page(
    client: httpx.Client,
    *,
    page: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    payload = request_json(
        client,
        "POST",
        LIST_PATH,
        json_body={"page": str(page), "limit": str(limit)},
    )
    if not isinstance(payload, dict):
        raise ScrapeError(f"Listing-payload heeft onverwacht formaat op pagina {page}")
    raw_results = payload.get("results")
    total_count = payload.get("total_count")
    if not isinstance(raw_results, list) or not isinstance(total_count, int):
        raise ScrapeError(f"Listing-payload heeft onverwacht formaat op pagina {page}")
    if not raw_results:
        raise ScrapeError(f"Listing-payload op pagina {page} bevat geen resultaten")
    return raw_results, total_count


def collect_algorithms(limit: int | None) -> list[AlgorithmDetail]:
    request_limit = min(limit, 100) if limit is not None else 100
    details: list[AlgorithmDetail] = []

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "algoritmeregister-scraper/1.0"},
    ) as client:
        first_page, total_count = fetch_listing_page(client, page=1, limit=request_limit)
        page_size = len(first_page)
        total_to_collect = min(total_count, limit) if limit is not None else total_count
        total_pages = math.ceil(total_to_collect / page_size)
        logging.info("Gevonden: %s algoritmes over %s pagina's", total_count, total_pages)

        records = list(first_page)
        for page in range(2, total_pages + 1):
            page_records, _ = fetch_listing_page(client, page=page, limit=request_limit)
            records.extend(page_records)

        if limit is not None:
            records = records[:limit]

        for index, item in enumerate(records, start=1):
            detail = build_detail(item)
            logging.info("Record %s/%s: %s", index, len(records), detail.title)
            details.append(detail)

    return details


def load_existing() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def first_seen_map(existing: dict[str, Any]) -> dict[str, str]:
    """Map id -> date the id was first observed, from the previous output."""
    return {
        item["id"]: item["toegevoegd"]
        for item in existing.get("algoritmes", [])
        if isinstance(item, dict) and item.get("id") and item.get("toegevoegd")
    }


def build_output(algoritmes: list[AlgorithmDetail], first_seen: dict[str, str]) -> dict[str, Any]:
    today = datetime.now(UTC).date().isoformat()
    sorted_records = sorted(
        (
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "organisatie": item.organisatie,
                "doel": item.doel,
                "juridische_basis": item.juridische_basis,
                "impactassessment": item.impactassessment,
                "status": item.status,
                "laatst_gewijzigd": item.laatst_gewijzigd,
                "toegevoegd": first_seen.get(item.id, today),
            }
            for item in algoritmes
        ),
        key=lambda item: item["id"],
    )
    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_url": SOURCE_URL,
        "count": len(sorted_records),
        "algoritmes": sorted_records,
    }


def write_output(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    DATA_PATH.write_text(serialized, encoding="utf-8")


def substantive_part(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "fetched_at"}


def is_unchanged(data: dict[str, Any], existing: dict[str, Any]) -> bool:
    if not existing:
        return False
    return substantive_part(existing) == substantive_part(data)


def main() -> int:
    configure_logging()
    args = parse_args()

    existing = load_existing()

    try:
        algoritmes = collect_algorithms(limit=args.limit)
        output = build_output(algoritmes, first_seen_map(existing))
    except ScrapeError as exc:
        logging.error("%s", exc)
        return 1

    if args.dry_run:
        preview = output["algoritmes"][:3]
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 0

    if is_unchanged(output, existing):
        logging.info("Geen inhoudelijke wijziging; %s ongewijzigd gelaten", DATA_PATH)
        return 0

    write_output(output)
    logging.info("Geschreven: %s", DATA_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
