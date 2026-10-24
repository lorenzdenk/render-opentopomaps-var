#!/usr/bin/env bash
# Gets the national hillshades of HILLSHADE_SOURCES (region file) for the current region: from the release
# "hillshade-data" if a run already downloaded them for the same area, otherwise from the tile service
# (fetch_hillshade.py), then stored in that release for the next runs and the other render jobs.
# Prints the paths of the GeoTIFFs in priority order (stdout); messages go to stderr.
# usage: hillshade_cache.sh <dir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
source "$HERE/region.env"
dir="$1"; mkdir -p "$dir"
IFS=, read -r W S E N <<< "$BBOX"
BUF=0.05   # as render.sh
BW=$(echo "$W - $BUF" | bc -l); BS=$(echo "$S - $BUF" | bc -l)
BE=$(echo "$E + $BUF" | bc -l); BN=$(echo "$N + $BUF" | bc -l)
LEVEL=${HILLSHADE_LEVEL:-14}
gh_ok=""; [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && gh_ok=1 && export GH_TOKEN="$GITHUB_TOKEN"
for src in ${HILLSHADE_SOURCES:-}; do
  key=$(echo "$src $LEVEL $BW $BS $BE $BN" | md5sum | cut -c1-10)
  f="$dir/hs-$src-z$LEVEL-$key.tif"
  if [ ! -s "$f" ] && [ -n "$gh_ok" ]; then
    gh release download hillshade-data -R "$GITHUB_REPOSITORY" -p "$(basename "$f")" -D "$dir" --clobber >&2 2>/dev/null \
      && echo "hillshade $src: from the release cache" >&2 || true
  fi
  if [ ! -s "$f" ]; then
    echo "hillshade $src: downloading level $LEVEL" >&2
    if python3 "$HERE/data/fetch_hillshade.py" "$src" "$LEVEL" "$BW" "$BS" "$BE" "$BN" "$f.tmp" 12 >&2; then
      mv "$f.tmp" "$f"
      if [ -n "$gh_ok" ]; then
        gh release view hillshade-data -R "$GITHUB_REPOSITORY" >/dev/null 2>&1 \
          || gh release create hillshade-data -R "$GITHUB_REPOSITORY" --latest=false -t "Hillshade data" \
               -n "Hillshade tiles as GeoTIFF: swisstopo swissALTI3D Reliefschattierung (© swisstopo), basemap.de Web Raster Hillshade (© GeoBasis-DE / BKG, CC BY 4.0)" >&2 \
          || true
        gh release upload hillshade-data -R "$GITHUB_REPOSITORY" "$f" --clobber >&2 || echo "WARN: hillshade cache upload failed" >&2
      fi
    else
      echo "WARN: hillshade $src failed" >&2; rm -f "$f.tmp"; continue
    fi
  fi
  echo "$f"
done
