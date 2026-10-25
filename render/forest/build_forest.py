#!/usr/bin/env python3
"""Forest type raster for Germany / Switzerland (classes of the map legend), Web Mercator, RES m:

  share of broadleaved trees: 1 conifers 0-10 %   2 mixed, mostly conifers 10-50 %
                              3 mixed, mostly broadleaved 50-90 %   4 broadleaved 90-100 %
  drawn separately where they dominate: 5 pine   6 birch
  8 canopy loss (clearing, Germany only)   0 no information (OSM forest there is drawn as 7 "no information")

Sources:
  Switzerland: Waldmischungsgrad LFI (BAFU, Sentinel-1/2, 2023), 10 m, share of broadleaved trees in %;
               pine from the Thurgau stand map (Forstliche Bestandeskarte, main tree species "Föhre")
  Germany: tree species map 2022, DLR / Thünen-Institut, 10 m (CC BY 4.0): the broadleaf share is the share of
           broadleaved pixels (beech, oak, birch, alder, other) among all tree pixels within SHARE_WIN pixels;
           pine, birch and canopy loss where they are the most frequent class within MAJORITY pixels

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
SIEVE = int(os.environ.get("FOREST_SIEVE", "120"))       # pixels: 120 x 25 m² = 0.3 ha
MAJORITY = int(os.environ.get("FOREST_MAJORITY", "7"))   # window (pixels) for pine / birch / loss in Germany
SHARE_WIN = int(os.environ.get("FOREST_SHARE_WIN", "11"))  # window (pixels) of the broadleaf share in Germany (55 m)
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/render-opentopomaps-var)"}

THUENEN = "/vsicurl/https://download.geoservice.dlr.de/TREE_SPECIES_DE/files/treespecies_de_2022.tif"
BAFU = "/vsicurl/https://data.geo.admin.ch/ch.bafu.landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad_2056.tif"
TG = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"

# Thünen codes (treespecies_de_2022.qml): 0 pine, 1 spruce, 2 Douglas fir, 3 larch, 4 fir, 5 beech, 6 oak, 7 birch,
# 8 alder, 9 other, 666 canopy cover loss
TH_CONIFER, TH_BROADLEAF, TH_PINE, TH_BIRCH, TH_LOSS = (0, 1, 2, 3, 4), (5, 6, 7, 8, 9), 0, 7, 666
# Thurgau "hauptbaum" codes (checked against the WMS legend colours): 0 Fichte, 1 Tanne, 2 Föhre, 3 Lärche,
# 4 andere Nadelhölzer, 5 Buche, 6 Eiche, 7 Esche, 8 Ahorn, 9 andere Laubhölzer. Only pine (Föhre) is used.
TG_MAP = {2: 5}
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


def boxsum(a, size):
    r = size // 2
    c = np.pad(a.astype(np.int32), r).cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return c[size:, size:] - c[:-size, size:] - c[size:, :-size] + c[:-size, :-size]


def share_classes(share):
    """broadleaf share in % -> classes 1-4 (0 where unknown)"""
    out = np.zeros(share.shape, np.uint8)
    ok = np.isfinite(share)
    out[ok] = np.select([share[ok] < 10, share[ok] < 50, share[ok] < 90], [1, 2, 3], 4)
    return out


def main():
    t0 = time.time()
    os.makedirs(WORK, exist_ok=True)
    m = osr.SpatialReference()
    m.ImportFromEPSG(3857)
    x0, y0, x1, y1 = bbox_in(3857)
    cols, rows = int((x1 - x0) / RES) + 1, int((y1 - y0) / RES) + 1
    bounds = (x0, y1 - rows * RES, x0 + cols * RES, y1)
    print(f"grid {cols} x {rows} px, {RES} m", flush=True)
    share = np.full((rows, cols), np.nan, np.float32)
    special = np.zeros((rows, cols), np.uint8)

    # Switzerland: broadleaf share
    try:
        info = gdal.Info(BAFU, format="json")
        print("BAFU raster:", info["bands"][0].get("type"), "nodata", info["bands"][0].get("noDataValue"), flush=True)
        a = warp(BAFU, bounds, cols, rows, gdal.GDT_Float32)
        nd = info["bands"][0].get("noDataValue")
        ok = (a >= 0) & np.isfinite(a) & ((a != nd) if nd is not None else True)
        if ok.any():
            hi = np.percentile(a[ok], 99.5)
            scale = 100.0 if hi <= 1.0 else (0.01 if hi > 100 else 1.0)   # fraction, per mille/10000 or percent
            print(f"BAFU: {ok.mean() * 100:.1f} % of the area, values {np.percentile(a[ok], [1, 25, 50, 75, 99]).round(2)},"
                  f" scale {scale}", flush=True)
            share[ok] = np.clip(a[ok] * scale, 0, 100)
    except Exception as e:
        print("WARN: BAFU failed:", e, flush=True)

    # Germany: share from the species, pine / birch / loss where they dominate
    try:
        qml = get(THUENEN.replace("/vsicurl/", "").replace(".tif", ".qml")).decode("utf-8", "replace")
        import re as _re
        print("Thünen legend:", _re.findall(r'label="([^"]+)" value="(\d+)"', qml), flush=True)
    except Exception as e:
        print("Thünen legend not read:", e, flush=True)
    try:
        a = warp(THUENEN, bounds, cols, rows)
        tree = np.isin(a, TH_CONIFER + TH_BROADLEAF)
        broad = np.isin(a, TH_BROADLEAF)
        n_tree, n_broad = boxsum(tree, SHARE_WIN), boxsum(broad, SHARE_WIN)
        de = (a >= 0) & (n_tree > 0)
        share[de] = 100.0 * n_broad[de] / n_tree[de]
        win = {k: boxsum(a == k, MAJORITY) for k in TH_CONIFER + TH_BROADLEAF + (TH_LOSS,)}
        best = np.max(np.stack(list(win.values())), axis=0)
        for k, c in ((TH_PINE, 5), (TH_BIRCH, 6), (TH_LOSS, 8)):
            special[(a >= 0) & (win[k] == best) & (win[k] > 0)] = c
        vals, cnt = np.unique(a[a >= 0], return_counts=True)
        print(f"Thünen tree species: {de.mean() * 100:.1f} % of the area, codes {dict(zip(vals.tolist(), cnt.tolist()))}",
              flush=True)
    except Exception as e:
        print("WARN: Thünen failed:", e, flush=True)

    # Thurgau: pine stands
    try:
        path = os.path.join(WORK, "thurgau_stands.geojson")
        feats = thurgau(path)
        print(f"Thurgau: {len(feats)} pine stands", flush=True)
        if feats:
            merc = os.path.join(WORK, "thurgau_stands_3857.gpkg")
            gdal.VectorTranslate(merc, path, format="GPKG", dstSRS="EPSG:3857", srcSRS="EPSG:2056",
                                 layerName="stands", makeValid=True)
            ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
            ds.SetGeoTransform((bounds[0], RES, 0, bounds[3], 0, -RES))
            ds.SetProjection(m.ExportToWkt())
            gdal.Rasterize(ds, merc, attribute="cls", layers=["stands"])
            t = ds.GetRasterBand(1).ReadAsArray()
            special = np.where(t > 0, t, special)
            print(f"Thurgau pine: {(t > 0).mean() * 100:.2f} % of the area", flush=True)
    except Exception as e:
        print("WARN: Thurgau failed:", e, flush=True)

    cls = share_classes(share)
    cls = np.where(special > 0, special, cls)
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
