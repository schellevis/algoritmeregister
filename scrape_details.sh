#!/usr/bin/env bash
# Haal lokaal alle detail-records van het Algoritmeregister op.
# Draait op deze VPS, NIET in de GitHub Action. Output: detail/<id>.json
# (los van data/algoritmes.json; koppelbaar via id == lars).
#
# Gebruik:
#   ./scrape_details.sh                 # resume: alleen ontbrekende id's
#   ./scrape_details.sh --force         # alles opnieuw ophalen
#   ./scrape_details.sh --limit 20      # eerste 20 (test)
#   ./scrape_details.sh --from-listing  # id-lijst live uit de API i.p.v. data/algoritmes.json
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --disable-pip-version-check -r requirements.txt

exec python scrape_details.py "$@"
