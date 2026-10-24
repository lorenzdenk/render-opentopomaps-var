#!/usr/bin/env python3
"""Forest type raster for Germany / Switzerland (classes of the map legend), Web Mercator, RES m:

  1 spruce / Douglas fir / fir   2 pine   3 larch   4 beech   5 oak   6 birch   7 other   8 canopy loss
  0 no information (OSM forest there is drawn as 7 "other")

Sources, in priority order:
  Thurgau: Forstliche Bestandeskarte (Kanton Thurgau, open use), main tree species per stand (WFS)
  Germany: tree species map 2022, DLR / Thünen-Institut, 10 m (CC BY 4.0)
  rest of Switzerland: Waldmischungsgrad LFI (BAFU), 10 m, share of broadleaved trees:
           below 40 % -> 1 (conifers), otherwise 7 (broadleaved / mixed)

Small specks (below SIEVE pixels) are merged into their neighbours.
Usage: build_forest.py <W> <S> <E> <N> <out.tif> [workdir]
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "5")
gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "3")
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
W, S, E, N = map(float, sys.argv[1:5])
OUT = sys.argv[5]
WORK = sys.argv[6] if len(sys.argv) > 6 else os.path.dirname(os.path.abspath(OUT))
RES = float(os.environ.get("FOREST_RES", "5"))
SIEVE = int(os.environ.get("FOREST_SIEVE", "24"))
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/render-opentopomaps-var)"}

THUENEN = "/vsicurl/https://download.geoservice.dlr.de/TREE_SPECIES_DE/files/treespecies_de_2022.tif"
BAFU = "/vsicurl/https://data.geo.admin.ch/ch.bafu.landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad_2056.tif"
TG = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"

# Thünen codes: 0 pine, 1 spruce, 2 Douglas fir, 3 larch, 4 fir, 5 beech, 6 oak, 7 birch, 8 alder, 9 other, 666 loss
THUENEN_MAP = {0: 2, 1: 1, 2: 1, 3: 3, 4: 1, 5: 4, 6: 5, 7: 6, 8: 7, 9: 7, 666: 8}
# Thurgau "hauptbaum" codes in the order of the WMS legend: 0 Fichte, 1 Tanne, 2 Föhre, 3 Lärche, 4 andere Nadelhölzer,
# 5 Buche, 6 Eiche, 7 Esche, 8 Ahorn, 9 andere Laubhölzer (checked against the WMS colours in the log)
TG_MAP = {0: 1, 1: 1, 2: 2, 3: 3, 4: 1, 5: 4, 6: 5, 7: 7, 8: 7, 9: 7}
TG_NAMES = ["Fichte", "Tanne", "Föhre", "Lärche", "andere Nadelhölzer", "Buche", "Eiche", "Esche", "Ahorn", "andere Laubhölzer"]


def get(url, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except Exception as e:
            print("  retry", repr(e)[:150], flush=True)
            time.sleep(3 * (i + 1))
    raise RuntimeError("failed: " + url)


def warp(src, bounds, cols, rows, dtype=gdal.GDT_Int16):
    ds = gdal.Warp("", src, format="MEM", dstSRS="EPSG:3857", outputBounds=bounds, width=cols, height=rows,
                   resampleAlg="near", outputType=dtype, dstNodata=-1)
    return ds.GetRasterBand(1).ReadAsArray()


def bbox_in(epsg):
    s, d = osr.SpatialReference(), osr.SpatialReference()
    s.ImportFromEPSG(4326), d.ImportFromEPSG(epsg)
    for r in (s, d):
        r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    t = osr.CoordinateTransformation(s, d)
    pts = [t.TransformPoint(x, y)[:2] for x in (W, E) for y in (S, N)]
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def thurgau(path):
    """All stands in the area from the WFS (GeoJSON pages of 3000), written as one GeoJSON file in EPSG:2056."""
    x0, y0, x1, y1 = bbox_in(2056)
    feats, start = [], 0
    while True:
        q = urllib.parse.urlencode({"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                    "typeNames": "ms:hauptbaumart", "count": 3000, "startIndex": start,
                                    "bbox": f"{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f},urn:ogc:def:crs:EPSG::2056",
                                    "srsName": "urn:ogc:def:crs:EPSG::2056", "outputFormat": "GEOJSON"})
        js = json.loads(get(f"{TG}?{q}"))
        page = js.get("features", [])
        feats += page
        print(f"  Thurgau: {len(feats)} stands", flush=True)
        if len(page) < 3000:
            break
        start += 3000
    out = []
    for f in feats:
        try:
            code = int(f["properties"].get("hauptbaum") or -1)
        except ValueError:
            code = -1
        if code in TG_MAP and f.get("geometry"):
            f["properties"] = {"cls": TG_MAP[code], "code": code}
            out.append(f)
    js = {"type": "FeatureCollection", "features": out,
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2056"}}}
    with open(path, "w") as fh:
        json.dump(js, fh)
    return out


def check_thurgau_codes(feats):
    """Log the WMS colour at one stand per code, to compare with the legend (Fichte light orange, Tanne pink, ...)."""
    by_code = {}
    for f in feats:
        c = f["properties"]["code"]
        g = ogr.CreateGeometryFromJson(json.dumps(f["geometry"]))
        if g and g.GetArea() > 5000 and c not in by_code:
            p = g.PointOnSurface()
            by_code[c] = (p.GetX(), p.GetY())
    for c in sorted(by_code):
        x, y = by_code[c]
        q = urllib.parse.urlencode({"service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": "hauptbaumart",
                                    "styles": "", "crs": "EPSG:2056", "bbox": f"{x - 2},{y - 2},{x + 2},{y + 2}",
                                    "width": 3, "height": 3, "format": "image/png", "transparent": "false"})
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(get(f"{TG}?{q}"))).convert("RGB")
            print(f"  Thurgau code {c} ({TG_NAMES[c]}): WMS colour #%02x%02x%02x" % im.getpixel((1, 1)), flush=True)
        except Exception as e:
            print(f"  Thurgau code {c}: WMS check failed {e}", flush=True)


def main():
    t0 = time.time()
    os.makedirs(WORK, exist_ok=True)
    m = osr.SpatialReference()
    m.ImportFromEPSG(3857)
    x0, y0, x1, y1 = bbox_in(3857)
    cols, rows = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
    bounds = (x0, y1 - rows * RES, x0 + cols * RES, y1)
    print(f"grid {cols} x {rows} px, {RES} m", flush=True)
    cls = np.zeros((rows, cols), np.uint8)

    # 3) rest of Switzerland: broadleaf share
    try:
        a = warp(BAFU, bounds, cols, rows)
        ok = (a >= 0) & (a <= 100)
        cls[ok] = np.where(a[ok] < 40, 1, 7)
        print(f"BAFU Waldmischungsgrad: {ok.mean() * 100:.1f} % of the area, values {np.unique(a)[:12]}", flush=True)
    except Exception as e:
        print("WARN: BAFU failed:", e, flush=True)

    # 2) Germany: tree species
    try:
        qml = get(THUENEN.replace("/vsicurl/", "").replace(".tif", ".qml")).decode("utf-8", "replace")
        import re as _re
        print("Thünen legend (qml):", _re.findall(r'<(?:paletteEntry|item)[^>]*>', qml)[:20], flush=True)
    except Exception as e:
        print("Thünen legend not read:", e, flush=True)
    try:
        a = warp(THUENEN, bounds, cols, rows)
        lut = np.zeros(1024, np.uint8)
        for k, v in THUENEN_MAP.items():
            lut[k] = v
        b = lut[np.clip(a, 0, 1023)] * (a >= 0)
        cls = np.where(b > 0, b, cls)
        vals, cnt = np.unique(a[a >= 0], return_counts=True)
        print(f"Thünen tree species: {(b > 0).mean() * 100:.1f} % of the area, codes {dict(zip(vals.tolist(), cnt.tolist()))}",
              flush=True)
    except Exception as e:
        print("WARN: Thünen failed:", e, flush=True)

    # 1) Thurgau stands
    try:
        path = os.path.join(WORK, "thurgau_stands.geojson")
        feats = thurgau(path)
        if feats:
            check_thurgau_codes(feats)
            ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
            ds.SetGeoTransform((bounds[0], RES, 0, bounds[3], 0, -RES))
            ds.SetProjection(m.ExportToWkt())
            merc = os.path.join(WORK, "thurgau_stands_3857.gpkg")
            gdal.VectorTranslate(merc, path, format="GPKG", dstSRS="EPSG:3857", srcSRS="EPSG:2056",
                                 layerName="stands", makeValid=True)
            gdal.Rasterize(ds, merc, attribute="cls", layers=["stands"])
            t = ds.GetRasterBand(1).ReadAsArray()
            cls = np.where(t > 0, t, cls)
            print(f"Thurgau: {(t > 0).mean() * 100:.1f} % of the area", flush=True)
    except Exception as e:
        print("WARN: Thurgau failed:", e, flush=True)

    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(OUT, cols, rows, 1, gdal.GDT_Byte, ["TILED=YES", "COMPRESS=DEFLATE"])
    ds.SetGeoTransform((bounds[0], RES, 0, bounds[3], 0, -RES))
    ds.SetProjection(m.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(cls)
    gdal.SieveFilter(band, None, band, SIEVE, 8)
    a = band.ReadAsArray()
    vals, cnt = np.unique(a, return_counts=True)
    print("classes (pixels):", dict(zip(vals.tolist(), cnt.tolist())), flush=True)
    ds = None
    print(f"written {OUT}, {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
