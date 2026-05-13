from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://algoritmes.overheid.nl"
LIST_PATH = "/nl/algoritme"
DATA_PATH = Path("data/algoritmes.json")
BACKOFF_SECONDS = (1, 4, 16)
PAYLOAD_RE = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>([\s\S]*?)</script>')
WHITESPACE_RE = re.compile(r"\s+")


class ScrapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlgorithmSummary:
    title: str
    organisatie: str
    beschrijving_kort: str
    status_bron: str
    create_dt: str
    org_id: str
    lars: str


@dataclass(frozen=True)
class AlgorithmDetail:
    title: str
    organisatie: str
    doel: str
    juridische_basis: str
    impactassessment: str
    status: str
    laatst_gewijzigd: str
    url: str
    id: str


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape het Algoritmeregister.")
    parser.add_argument("--dry-run", action="store_true", help="Print eerste 3 records, schrijf niets.")
    parser.add_argument("--limit", type=int, default=None, help="Beperk het aantal records.")
    return parser.parse_args()


def fetch_with_retries(client: httpx.Client, url: str) -> str:
    last_error: Exception | None = None
    for attempt, backoff in enumerate(BACKOFF_SECONDS, start=1):
        try:
            response = client.get(url)
            if response.status_code == 429:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                wait_seconds = retry_after if retry_after is not None else backoff
                logging.warning("429 ontvangen voor %s; wacht %ss", url, wait_seconds)
                time.sleep(wait_seconds)
                continue
            if 500 <= response.status_code < 600:
                logging.warning("Serverfout %s voor %s", response.status_code, url)
                time.sleep(backoff)
                continue
            if 400 <= response.status_code < 500:
                raise ScrapeError(f"Clientfout {response.status_code} voor {url}")

            response.raise_for_status()
            text = response.text
            if not text.strip():
                logging.warning("Lege response voor %s", url)
                raise ScrapeError(f"Lege response voor {url}")
            return text
        except httpx.HTTPError as exc:
            last_error = exc
            logging.warning("Netwerkfout bij %s (poging %s/3): %s", url, attempt, exc)
            time.sleep(backoff)
        except ScrapeError:
            raise

    if last_error is not None:
        raise ScrapeError(f"Mislukt na retries voor {url}: {last_error}") from last_error
    raise ScrapeError(f"Mislukt na retries voor {url}")


def parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    if value.isdigit():
        return int(value)
    try:
        retry_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    delta = retry_at - datetime.now(retry_at.tzinfo or UTC)
    return max(0, math.ceil(delta.total_seconds()))


def extract_payload(html: str) -> list[Any]:
    match = PAYLOAD_RE.search(html)
    if match is None:
        raise ScrapeError("Kon __NUXT_DATA__ payload niet vinden")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ScrapeError(f"Kon payload niet parsen als JSON: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise ScrapeError("Payload heeft onverwacht formaat")
    return payload


def decode_nuxt_value(node: Any, root: list[Any], seen: dict[int, Any] | None = None) -> Any:
    if seen is None:
        seen = {}

    if isinstance(node, int) and 0 <= node < len(root):
        if node in seen:
            return seen[node]
        target = root[node]
        if isinstance(target, dict):
            placeholder: dict[str, Any] = {}
            seen[node] = placeholder
            placeholder.update(decode_nuxt_value(target, root, seen))
            return placeholder
        if isinstance(target, list):
            placeholder_list: list[Any] = []
            seen[node] = placeholder_list
            placeholder_list.extend(decode_nuxt_value(target, root, seen))
            return placeholder_list
        return target

    if isinstance(node, dict):
        return {key: decode_nuxt_value(value, root, seen) for key, value in node.items()}

    if isinstance(node, list):
        if node and node[0] in {"ShallowReactive", "Reactive"}:
            return decode_nuxt_value(node[1], root, seen) if len(node) > 1 else []
        if node and node[0] == "Set":
            return [decode_nuxt_value(value, root, seen) for value in node[1:]]
        return [decode_nuxt_value(value, root, seen) for value in node]

    return node


def find_listing_payload(payload: list[Any]) -> dict[str, Any]:
    for item in payload:
        if isinstance(item, dict) and {"results", "total_count"} <= set(item.keys()):
            return decode_nuxt_value(item, payload)
    raise ScrapeError("Kon listing-payload niet vinden")


def find_detail_payload(payload: list[Any]) -> dict[str, Any]:
    for item in payload:
        if isinstance(item, dict) and {"name", "organization", "create_dt", "lars"} <= set(item.keys()):
            return decode_nuxt_value(item, payload)
    raise ScrapeError("Kon detail-payload niet vinden")


def html_fragment_to_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return normalize_whitespace(str(value))
    if "<" not in value and ">" not in value:
        return normalize_whitespace(unescape(value))
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return normalize_whitespace(unescape(text))


def normalize_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_status(value: str) -> str:
    normalized = normalize_whitespace(value).lower()
    mapping = {
        "in gebruik": "in_gebruik",
        "in ontwikkeling": "ontwikkeling",
        "uitgefaseerd": "uitgefaseerd",
    }
    return mapping.get(normalized, normalized.replace(" ", "_"))


def normalize_impactassessment(detail: dict[str, Any]) -> str:
    candidates = [
        html_fragment_to_text(detail.get("impacttoetsen")),
        html_fragment_to_text(detail.get("impacttoetsen_grouping")),
        html_fragment_to_text(detail.get("iama")),
        html_fragment_to_text(detail.get("iama_description")),
        html_fragment_to_text(detail.get("dpia")),
        html_fragment_to_text(detail.get("dpia_description")),
    ]
    joined = " ".join(candidate for candidate in candidates if candidate).strip().lower()
    if not joined:
        return "Onbekend"
    if joined == "geen":
        return "Nee"
    return "Ja"


def build_summary(item: dict[str, Any]) -> AlgorithmSummary:
    lars_value = item.get("lars")
    if lars_value is None:
        raise ScrapeError("Listing-item mist lars")
    return AlgorithmSummary(
        title=normalize_whitespace(str(item.get("name", ""))),
        organisatie=normalize_whitespace(str(item.get("organization", ""))),
        beschrijving_kort=html_fragment_to_text(item.get("description_short")),
        status_bron=normalize_whitespace(str(item.get("status", ""))),
        create_dt=normalize_whitespace(str(item.get("create_dt", ""))),
        org_id=normalize_whitespace(str(item.get("org_id", ""))),
        lars=normalize_whitespace(str(lars_value)),
    )


def build_detail(summary: AlgorithmSummary, detail: dict[str, Any]) -> AlgorithmDetail:
    detail_lars = normalize_whitespace(str(detail.get("lars", "")))
    if detail_lars != summary.lars:
        raise ScrapeError(f"Detail-ID mismatch voor {summary.lars}: {detail_lars}")

    create_dt = normalize_whitespace(str(detail.get("create_dt", summary.create_dt)))
    if not create_dt:
        raise ScrapeError(f"Detail mist create_dt voor {summary.lars}")

    return AlgorithmDetail(
        id=summary.lars,
        title=normalize_whitespace(str(detail.get("name", summary.title))),
        url=f"{BASE_URL}/nl/algoritme/{summary.lars}",
        organisatie=normalize_whitespace(str(detail.get("organization", summary.organisatie))),
        doel=html_fragment_to_text(detail.get("goal")),
        juridische_basis=html_fragment_to_text(detail.get("lawful_basis")),
        impactassessment=normalize_impactassessment(detail),
        status=normalize_status(normalize_whitespace(str(detail.get("status", summary.status_bron)))),
        laatst_gewijzigd=create_dt[:10],
    )


def scrape_listing_page(client: httpx.Client, page: int) -> tuple[list[AlgorithmSummary], int]:
    html = fetch_with_retries(client, f"{BASE_URL}{LIST_PATH}?page={page}")
    payload = extract_payload(html)
    listing = find_listing_payload(payload)
    raw_results = listing.get("results")
    total_count = listing.get("total_count")
    if not isinstance(raw_results, list) or not isinstance(total_count, int):
        raise ScrapeError(f"Listing-payload heeft onverwacht formaat op pagina {page}")
    return [build_summary(item) for item in raw_results], total_count


def scrape_detail_page(client: httpx.Client, summary: AlgorithmSummary) -> AlgorithmDetail:
    html = fetch_with_retries(client, f"{BASE_URL}{LIST_PATH}/{summary.lars}")
    payload = extract_payload(html)
    detail = find_detail_payload(payload)
    return build_detail(summary, detail)


def collect_algorithms(limit: int | None) -> list[AlgorithmDetail]:
    summaries: list[AlgorithmSummary] = []
    details: list[AlgorithmDetail] = []

    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "algoritmeregister-scraper/1.0"}) as client:
        first_page_summaries, total_count = scrape_listing_page(client, page=1)
        if not first_page_summaries:
            raise ScrapeError("Geen resultaten gevonden op pagina 1")
        summaries.extend(first_page_summaries)
        page_size = len(first_page_summaries)
        total_pages = math.ceil(total_count / page_size)
        logging.info("Gevonden: %s algoritmes over %s pagina's", total_count, total_pages)

        for page in range(2, total_pages + 1):
            if limit is not None and len(summaries) >= limit:
                break
            page_summaries, _ = scrape_listing_page(client, page=page)
            summaries.extend(page_summaries)

        if limit is not None:
            summaries = summaries[:limit]

        for index, summary in enumerate(summaries, start=1):
            logging.info("Detail %s/%s: %s", index, len(summaries), summary.title)
            details.append(scrape_detail_page(client, summary))

    return details


def build_output(algoritmes: list[AlgorithmDetail]) -> dict[str, Any]:
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
            }
            for item in algoritmes
        ),
        key=lambda item: item["id"],
    )
    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_url": f"{BASE_URL}{LIST_PATH}",
        "count": len(sorted_records),
        "algoritmes": sorted_records,
    }


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        algoritmes = collect_algorithms(limit=args.limit)
        output = build_output(algoritmes)
    except ScrapeError as exc:
        logging.error("%s", exc)
        return 1

    if args.dry_run:
        preview = output["algoritmes"][:3]
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 0

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
