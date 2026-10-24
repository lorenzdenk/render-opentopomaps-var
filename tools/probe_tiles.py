#!/usr/bin/env python3
"""Average tile size of a LIST MapServer tile cache over Tasmania (runs on GitHub: theLIST is not reachable
from the development machine). Usage: probe_tiles.py <service> <minzoom> <maxzoom> <logdir>"""
import json, math, random, sys, urllib.request
svc, z0, z1, LOG = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/lorimaps-render)"}
BASE = f"https://services.thelist.tas.gov.au/arcgis/rest/services/{svc}/MapServer"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def tile(lat, lon, z):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)


info = json.loads(get(BASE + "?f=json"))
lods = (info.get("tileInfo") or {}).get("lods") or []
z1 = min(z1, max((l["level"] for l in lods), default=z1))
json.dump({k: info.get(k) for k in ("copyrightText", "description", "serviceDescription", "exportTilesAllowed",
           "maxExportTilesCount", "minScale", "maxScale", "layers")}, open(f"{LOG}/{svc.replace('/', '_')}-info.json", "w"), indent=1)
random.seed(2)
# land points: random points in the bounding box of the main island, kept if the tile at zoom 8 is not sea-blue
pts = [(random.uniform(-43.6, -40.7), random.uniform(144.7, 148.3)) for _ in range(100)]
with open(f"{LOG}/tile_sizes.txt", "a") as fo:
    for z in range(z0, z1 + 1):
        sizes, missing, fmts = [], 0, {}
        for lat, lon in pts:
            x, y = tile(lat, lon, z)
            try:
                d = get(f"{BASE}/tile/{z}/{y}/{x}")
                sizes.append(len(d))
                k = "jpg" if d[:2] == b"\xff\xd8" else "png" if d[:4] == b"\x89PNG" else "other"
                fmts[k] = fmts.get(k, 0) + 1
            except Exception:
                missing += 1
        sizes.sort()
        med = sizes[len(sizes) // 2] if sizes else 0
        line = (f"{svc} z{z}: {len(sizes)} tiles, {missing} missing, avg {sum(sizes) / max(1, len(sizes)) / 1024:.1f} KB, "
                f"median {med / 1024:.1f} KB, formats {fmts}")
        print(line, flush=True)
        fo.write(line + "\n")
for name, lat, lon in (("cradle", -41.66, 145.95), ("hobart", -42.88, 147.32), ("tahune", -43.10, 146.72)):
    for z in (12, 14, 15, 16, 17):
        x, y = tile(lat, lon, z)
        try:
            d = get(f"{BASE}/tile/{z}/{y}/{x}")
            open(f"{LOG}/sample-{name}-z{z}." + ("jpg" if d[:2] == b"\xff\xd8" else "png"), "wb").write(d)
        except Exception as e:
            print("sample", name, z, e)
