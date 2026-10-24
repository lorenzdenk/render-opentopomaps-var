#!/usr/bin/env python3
"""Downloads LIST OpenDataWFS layers for all of Tasmania (CC BY 3.0 AU), in parallel grid cells
(the service returns at most 2000 features per request), and writes one GeoJSONSeq file per layer
(one feature per line, written as it comes: millions of contour lines do not fit in memory).
Usage: prepare_list_data.py <out dir> <layer>:<name>:<fields> ...
       e.g. 16:contours:ELEVATION 23:hydro_lines:HYDLNTY1,HYDLNTY2,HYD_CLASS,NAME
       optional 4th part: SQL where clause (e.g. to leave out the huge sea polygons).
A cell that keeps failing (server error on very large geometries) is split into four smaller cells."""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = sys.argv[1]
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/lorimaps-render)"}
W, S, E, N = 143.5, -43.9, 148.6, -39.3     # Tasmania with King and Flinders Island
STEP = 0.25


def fetch_cell(args, depth=0):
    layer, fields, where, w, s, e, n = args
    url = f"https://services.thelist.tas.gov.au/arcgis/rest/services/Public/OpenDataWFS/MapServer/{layer}/query"
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": where, "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "OBJECTID," + fields, "outSR": 4326,
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 2000, "f": "geojson"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url + "?" + q, headers=UA), timeout=300) as r:
                    page = json.load(r)
                break
            except Exception as ex:
                print(f"retry layer {layer} cell {w},{s} offset {offset}: {ex}", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            if depth < 3:
                print(f"splitting cell {w},{s} of layer {layer}", flush=True)
                mx, my = (w + e) / 2, (s + n) / 2
                out = []
                for c in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
                    out += fetch_cell((layer, fields, where) + c, depth + 1)
                return out
            raise SystemExit(f"ERROR: layer {layer} cell {w},{s} failed")
        part = page.get("features", [])
        feats += part
        if len(part) < 2000 and not page.get("exceededTransferLimit"):
            return feats
        offset += len(part)


for spec in sys.argv[2:]:
    parts = spec.split(":", 3)
    layer, name, fields = parts[:3]
    where = parts[3] if len(parts) > 3 else "1=1"
    cells = []
    x = W
    while x < E:
        y = S
        while y < N:
            cells.append((layer, fields, where, round(x, 4), round(y, 4), round(min(x + STEP, E), 4), round(min(y + STEP, N), 4)))
            y += STEP
        x += STEP
    t0 = time.time()
    seen, n = set(), 0
    with open(f"{OUT}/{name}.geojsonl", "w") as out, ThreadPoolExecutor(8) as pool:
        for i, feats in enumerate(pool.map(fetch_cell, cells)):
            for f in feats:       # features crossing cell borders come several times
                oid = f.get("properties", {}).get("OBJECTID", f.get("id"))
                if oid in seen:
                    continue
                seen.add(oid)
                out.write(json.dumps(f) + "\n")
                n += 1
            if i % 40 == 0:
                print(f"layer {layer} ({name}): {i + 1}/{len(cells)} cells, {n} features, "
                      f"{(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"layer {layer} ({name}): {n} features in {(time.time() - t0) / 60:.1f} min", flush=True)
