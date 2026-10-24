#!/usr/bin/env bash
# Prepared rasters of the current region, made once and kept in the release "prepared-data" (reused by the other
# render jobs and later runs of the same area). The asset name contains the area and a hash of the making script,
# so a changed script makes a new file.
#   fine-dem  fine elevation model for the contours (FINE_DEM=1, data/fine_dem.py)
#   forest    forest type classes (FOREST_TYPES=1, forest/build_forest.py)
# Prints the path of the file (stdout); messages go to stderr. Exit code 1 if it could not be made.
# usage: prepared.sh <kind> <dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/region.env"
kind="$1"; dir="$2"; mkdir -p "$dir"
IFS=, read -r W S E N <<< "$BBOX"
BUF=0.05   # as render.sh
BW=$(echo "$W - $BUF" | bc -l); BS=$(echo "$S - $BUF" | bc -l)
BE=$(echo "$E + $BUF" | bc -l); BN=$(echo "$N + $BUF" | bc -l)
case "$kind" in
  fine-dem) script="$HERE/data/fine_dem.py";      cmd=(python3 "$script" "$BW" "$BS" "$BE" "$BN" -) ;;
  forest)   script="$HERE/forest/build_forest.py"; cmd=(python3 "$script" "$BW" "$BS" "$BE" "$BN") ;;
  *) echo "unknown kind $kind" >&2; exit 2 ;;
esac
key=$( (echo "$BW $BS $BE $BN ${FINE_DEM_RES:-} ${FOREST_RES:-}"; cat "$script") | md5sum | cut -c1-10)
f="$dir/$kind-$key.tif"
gh_ok=""; [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && gh_ok=1 && export GH_TOKEN="$GITHUB_TOKEN"
if [ ! -s "$f" ] && [ -n "$gh_ok" ]; then
  gh release download prepared-data -R "$GITHUB_REPOSITORY" -p "$(basename "$f")" -D "$dir" --clobber >/dev/null 2>&1 \
    && echo "$kind: from the release cache" >&2 || true
fi
if [ ! -s "$f" ]; then
  echo "$kind: making $(basename "$f")" >&2
  if "${cmd[@]}" "$f.tmp.tif" "$dir/work-$kind" >&2; then
    mv "$f.tmp.tif" "$f"
    if [ -n "$gh_ok" ]; then
      gh release view prepared-data -R "$GITHUB_REPOSITORY" >/dev/null 2>&1 \
        || gh release create prepared-data -R "$GITHUB_REPOSITORY" --latest=false -t "Prepared data" \
             -n "Rasters prepared for rendering: fine elevation model (swissALTI3D © swisstopo, DGM1 LGL www.lgl-bw.de dl-de/by-2-0, Copernicus DEM) and forest types (DLR/Thünen CC BY 4.0, Kanton Thurgau, BAFU)" >&2 \
        || true
      gh release upload prepared-data -R "$GITHUB_REPOSITORY" "$f" --clobber >&2 || echo "WARN: upload of $kind failed" >&2
    fi
  else
    echo "WARN: $kind could not be made" >&2; rm -f "$f.tmp.tif"; exit 1
  fi
fi
echo "$f"
