#!/usr/bin/env python3
"""Probe: Thurgau stand map - all values of 'mischungsg' (mixture) in the test area, their meaning (WMS GetFeatureInfo
text and colour of the 'mischung' layer) and cross tables with main tree species and development stage."""
import collections, io, json, sys, urllib.parse, urllib.request
from osgeo import ogr
from PIL import Image
OUT = sys.argv[1]
BASE = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"
UA = {"User-Agent": "LoriMaps-render probe"}
def get(q):
    with urllib.request.urlopen(urllib.request.Request(BASE + "?" + urllib.parse.urlencode(q), headers=UA), timeout=180) as r:
        return r.read()
feats, start = [], 0
while True:
    js = json.loads(get({"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "ms:mischung",
                         "count": 3000, "startIndex": start, "srsName": "urn:ogc:def:crs:EPSG::2056",
                         "bbox": "2722000,1265000,2738000,1281000,urn:ogc:def:crs:EPSG::2056", "outputFormat": "GEOJSON"}))
    feats += js["features"]
    if len(js["features"]) < 3000:
        break
    start += 3000
print("stands:", len(feats))
P = lambda f, k: (f["properties"].get(k) or "").strip()
area = collections.Counter()
for f in feats:
    try:
        area[P(f, "mischungsg")] += float(P(f, "are") or 0)
    except ValueError:
        pass
cnt = collections.Counter(P(f, "mischungsg") for f in feats)
print("mischungsg: count / area (ha):")
for k, n in sorted(cnt.items()):
    print(f"  '{k}': {n} stands, {area[k] / 100:.0f} ha")
print("mischungsg x hauptbaum:")
ct = collections.Counter((P(f, "mischungsg"), P(f, "hauptbaum")) for f in feats)
for m in sorted(cnt):
    print(f"  {m!r}: " + ", ".join(f"{h}:{ct[(m, h)]}" for h in map(str, range(10)) if ct[(m, h)]))
print("mischungsg x entwstufe:")
ct = collections.Counter((P(f, "mischungsg"), P(f, "entwstufe")) for f in feats)
for m in sorted(cnt):
    print(f"  {m!r}: " + ", ".join(f"{e}:{ct[(m, e)]}" for e in map(str, range(10)) if ct[(m, e)]))
# meaning: GetFeatureInfo text and colour at one big stand per value
seen = {}
for f in sorted(feats, key=lambda f: -float(P(f, "are") or 0)):
    m = P(f, "mischungsg")
    if m in seen or not f.get("geometry"):
        continue
    g = ogr.CreateGeometryFromJson(json.dumps(f["geometry"])).PointOnSurface()
    seen[m] = (g.GetX(), g.GetY(), P(f, "objectid"), P(f, "hauptbaum"), P(f, "entwstufe"))
for m, (x, y, oid, hb, es) in sorted(seen.items()):
    bb = f"{x - 5},{y - 5},{x + 5},{y + 5}"
    base = {"service": "WMS", "version": "1.3.0", "crs": "EPSG:2056", "bbox": bb, "width": 11, "height": 11,
            "layers": "mischung", "styles": ""}
    try:
        col = Image.open(io.BytesIO(get({**base, "request": "GetMap", "format": "image/png", "transparent": "false"}))).convert("RGB").getpixel((5, 5))
    except Exception as e:
        col = repr(e)[:80]
    txt = ""
    for fmt in ("text/plain", "text/html", "application/vnd.ogc.gml"):
        try:
            t = get({**base, "request": "GetFeatureInfo", "query_layers": "mischung", "info_format": fmt, "i": 5, "j": 5,
                     "feature_count": 1}).decode("utf-8", "replace")
            if t.strip():
                txt = " ".join(t.split())[:900]
                break
        except Exception as e:
            txt = repr(e)[:120]
    print(f"\nmischungsg {m!r} (stand {oid}, hauptbaum {hb}, entwstufe {es}): WMS colour {col}\n  info: {txt}")
