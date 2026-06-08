from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DATA_PATH = Path("data/algoritmes.json")
NTFY_URL = "https://ntfy.sh"
URGENT_ORG_RE = re.compile(
    r"^(Ministerie|Gemeente (Amsterdam|Rotterdam|Utrecht|Den Haag))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Event:
    algoritme_id: str
    event_type: str
    severity: str
    organisatie: str
    summary: str
    fields_changed: tuple[str, ...]


class AlertError(RuntimeError):
    pass


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verstuur alerts op basis van git-diffs.")
    parser.add_argument("--since", default="HEAD~1", help="Oude commit of ref om tegen te diffen.")
    parser.add_argument("--dry-run", action="store_true", help="Bepaal events maar verstuur niets.")
    return parser.parse_args()


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def load_json_from_ref(ref: str) -> dict[str, Any]:
    result = run_git("show", f"{ref}:data/algoritmes.json", check=False)
    if result.returncode != 0:
        return {"algoritmes": []}
    return json.loads(result.stdout)


def load_current_json() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def build_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in data.get("algoritmes", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def changed_fields(old: dict[str, Any], new: dict[str, Any]) -> tuple[str, ...]:
    fields = sorted(
        key
        for key in set(old) | set(new)
        if key != "id" and old.get(key) != new.get(key)
    )
    return tuple(fields)


def classify_severity(
    event_type: str,
    organisatie: str,
    fields: tuple[str, ...],
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> str:
    if URGENT_ORG_RE.search(organisatie):
        return "urgent"
    if "impactassessment" in fields:
        return "urgent"
    if "juridische_basis" in fields:
        return "notable"
    old_status = old.get("status") if old else None
    new_status = new.get("status") if new else None
    if event_type == "changed" and old_status != "uitgefaseerd" and new_status == "uitgefaseerd":
        return "notable"
    return "info"


def summarize_event(
    event_type: str,
    algoritme_id: str,
    organisatie: str,
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    fields: tuple[str, ...],
) -> str:
    title = (new or old or {}).get("title", algoritme_id)
    if event_type == "added":
        return f"Nieuw algoritme: {title} ({algoritme_id})"
    if event_type == "removed":
        return f"Algoritme verwijderd: {title} ({algoritme_id})"
    field_list = ", ".join(fields) if fields else "onbekende velden"
    return f"Algoritme gewijzigd: {title} ({algoritme_id}); velden: {field_list}"


def diff_events(old_data: dict[str, Any], new_data: dict[str, Any]) -> list[Event]:
    old_index = build_index(old_data)
    new_index = build_index(new_data)
    events: list[Event] = []

    for algoritme_id in sorted(new_index.keys() - old_index.keys()):
        new_item = new_index[algoritme_id]
        organisatie = str(new_item.get("organisatie", "Onbekend"))
        severity = classify_severity("added", organisatie, tuple(), None, new_item)
        events.append(
            Event(
                algoritme_id=algoritme_id,
                event_type="added",
                severity=severity,
                organisatie=organisatie,
                summary=summarize_event("added", algoritme_id, organisatie, None, new_item, tuple()),
                fields_changed=tuple(),
            )
        )

    for algoritme_id in sorted(old_index.keys() - new_index.keys()):
        old_item = old_index[algoritme_id]
        organisatie = str(old_item.get("organisatie", "Onbekend"))
        severity = classify_severity("removed", organisatie, tuple(), old_item, None)
        events.append(
            Event(
                algoritme_id=algoritme_id,
                event_type="removed",
                severity=severity,
                organisatie=organisatie,
                summary=summarize_event("removed", algoritme_id, organisatie, old_item, None, tuple()),
                fields_changed=tuple(),
            )
        )

    for algoritme_id in sorted(old_index.keys() & new_index.keys()):
        old_item = old_index[algoritme_id]
        new_item = new_index[algoritme_id]
        fields = changed_fields(old_item, new_item)
        if not fields:
            continue
        organisatie = str(new_item.get("organisatie") or old_item.get("organisatie") or "Onbekend")
        severity = classify_severity("changed", organisatie, fields, old_item, new_item)
        events.append(
            Event(
                algoritme_id=algoritme_id,
                event_type="changed",
                severity=severity,
                organisatie=organisatie,
                summary=summarize_event("changed", algoritme_id, organisatie, old_item, new_item, fields),
                fields_changed=fields,
            )
        )

    return events


def priority_for_severity(severity: str) -> str:
    return {"urgent": "5", "notable": "3", "info": "2"}[severity]


def github_diff_url() -> str:
    repo = os.getenv("GITHUB_REPO")
    sha = os.getenv("GITHUB_SHA")
    if repo and sha:
        return f"https://github.com/{repo}/commit/{sha}"
    current_sha = run_git("rev-parse", "HEAD").stdout.strip()
    remote_url = run_git("config", "--get", "remote.origin.url", check=False).stdout.strip()
    if remote_url.startswith("https://github.com/"):
        base = remote_url.removesuffix(".git")
        return f"{base}/commit/{current_sha}"
    return current_sha


def ntfy_headers(event: Event) -> dict[str, str]:
    headers = {
        "Title": f"Algoritmeregister: {event.organisatie}",
        "Priority": priority_for_severity(event.severity),
        "Tags": f"{event.severity},algoritmeregister",
    }
    auth = os.getenv("NTFY_AUTH")
    if auth:
        headers["Authorization"] = auth
    return headers


def post_event(client: httpx.Client, topic: str, event: Event, diff_url: str) -> None:
    response = client.post(
        f"{NTFY_URL}/{topic}",
        headers=ntfy_headers(event),
        content=f"[{event.severity}] {event.summary}\n{diff_url}",
    )
    response.raise_for_status()


def build_summary_event(events: list[Event]) -> Event:
    counts: dict[str, int] = {"urgent": 0, "notable": 0, "info": 0}
    for event in events:
        counts[event.severity] += 1
    severity = "urgent" if counts["urgent"] else "notable" if counts["notable"] else "info"
    summary = (
        f"{len(events)} wijzigingen: "
        f"{counts['urgent']} urgent, {counts['notable']} notable, {counts['info']} info"
    )
    return Event(
        algoritme_id="summary",
        event_type="summary",
        severity=severity,
        organisatie="Meerdere organisaties",
        summary=summary,
        fields_changed=tuple(),
    )


def main() -> int:
    configure_logging()
    args = parse_args()

    run_git("diff", args.since, "HEAD", "--", "data/algoritmes.json", check=False)

    try:
        old_data = load_json_from_ref(args.since)
        new_data = load_current_json()
    except (AlertError, json.JSONDecodeError) as exc:
        logging.error("%s", exc)
        return 1

    events = diff_events(old_data, new_data)
    if not events:
        logging.info("Geen relevante wijzigingen gevonden.")
        return 0

    diff_url = github_diff_url()
    payload_events = [build_summary_event(events)] if len(events) > 10 else events

    if args.dry_run:
        print(
            json.dumps(
                [
                    {
                        "id": event.algoritme_id,
                        "type": event.event_type,
                        "severity": event.severity,
                        "organisatie": event.organisatie,
                        "summary": event.summary,
                        "fields_changed": list(event.fields_changed),
                    }
                    for event in payload_events
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        logging.error("NTFY_TOPIC ontbreekt")
        return 1

    with httpx.Client(timeout=30.0) as client:
        for event in payload_events:
            post_event(client, topic, event, diff_url)
            logging.info("Verstuurd: %s", event.summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
