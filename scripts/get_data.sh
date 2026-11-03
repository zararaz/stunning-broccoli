#!/usr/bin/env bash
# Extract the Yelp files this project needs into data/.
#
# Usage: scripts/get_data.sh <path to Yelp-JSON.zip | yelp_dataset.tar>
#
# Get the archive from https://business.yelp.com/data/resources/open-dataset/
# ("Download JSON"). Works with the .zip as downloaded, or the .tar inside it.
set -euo pipefail

FILES=(yelp_academic_dataset_business.json yelp_academic_dataset_checkin.json yelp_academic_dataset_tip.json)
DATA="$(cd "$(dirname "$0")/.." && pwd)/data"
mkdir -p "$DATA"

missing=()
for f in "${FILES[@]}"; do [[ -s "$DATA/$f" ]] || missing+=("$f"); done
if [[ ${#missing[@]} -eq 0 ]]; then
  echo "data/ already has all Yelp files; nothing to do."
  exit 0
fi

SRC="${1:-}"
if [[ -z "$SRC" || ! -f "$SRC" ]]; then
  echo "Usage: scripts/get_data.sh <path to Yelp-JSON.zip or yelp_dataset.tar>" >&2
  echo "Download it from https://business.yelp.com/data/resources/open-dataset/" >&2
  exit 1
fi

echo "Extracting ${missing[*]} into data/ (about a minute)..."
case "$SRC" in
  *.zip)
    # The .tar inside Yelp's zip is gzip-compressed; check its first bytes to be sure.
    magic=$(unzip -p "$SRC" "*.tar" -x "__MACOSX/*" | head -c 2 | od -An -tx1 | tr -d ' \n') || true
    z=""; [[ "$magic" == "1f8b" ]] && z="z"
    unzip -p "$SRC" "*.tar" -x "__MACOSX/*" | tar -x${z} -C "$DATA" -f - "${missing[@]}" ;;
  *.tar) tar -x -C "$DATA" -f "$SRC" "${missing[@]}" ;;
  *) echo "Expected a .zip or .tar file, got: $SRC" >&2; exit 1 ;;
esac
ls -lh "$DATA"/yelp_academic_dataset_*.json
