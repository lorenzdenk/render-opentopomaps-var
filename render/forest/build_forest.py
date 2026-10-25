#!/usr/bin/env python3
"""Forest type raster for Germany / Switzerland (classes of the map legend), Web Mercator, RES m:

  share of broadleaved trees: 1 conifers 0-10 %   2 mixed, mostly conifers 10-50 %
                              3 mixed, mostly broadleaved 50-90 %   4 broadleaved 90-100 %
  0 no information (OSM forest there is drawn as 7 "no information")

Sources (broadleaf share in %):
  Thurgau: Forstliche Bestandeskarte, mixture per stand (codes 1-4 = the four classes; 0 and 5-9 have no legend)
  Switzerland (and Thurgau stands without mixture): Waldmischungsgrad LFI (BAFU, Sentinel-1/2, 2023), 10 m
  Germany: tree species map 2022, DLR / Thünen-Institut, 10 m (CC BY 4.0): share of broadleaved pixels (beech, oak,
           birch, alder, other) among all tree pixels within SHARE_WIN pixels
Gaps without information up to about 2 x FILL_DIST pixels wide take the share of their surroundings.
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
FILL_DIST = int(os.environ.get("FOREST_FILL_DIST", "12"))  # pixels (60 m): gaps are filled from this far
SHARE_WIN = int(os.environ.get("FOREST_SHARE_WIN", "11"))  # window (pixels) of the broadleaf share in Germany (55 m)
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/render-opentopomaps-var)"}

THUENEN = "/vsicurl/https://download.geoservice.dlr.de/TREE_SPECIES_DE/files/treespecies_de_2022.tif"
BAFU = "/vsicurl/https://data.geo.admin.ch/ch.bafu.landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad/landesforstinventar-waldmischungsgrad_2056.tif"
TG = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"

# Thünen codes (treespecies_de_2022.qml): 0 pine, 1 spruce, 2 Douglas fir, 3 larch, 4 fir, 5 beech, 6 oak, 7 birch,
# 8 alder, 9 other, 666 canopy cover loss
TH_CONIFER, TH_BROADLEAF = (0, 1, 2, 3, 4), (5, 6, 7, 8, 9)
# Thurgau "mischungsg" codes (colours of the WMS layer "mischung" checked): 1 = 0-10 %, 2 = 10-50 %, 3 = 50-90 %,
# 4 = 90-100 % broadleaved; as share the middle of the class
TG_SHARE = {1: 5.0, 2: 30.0, 3: 70.0, 4: 95.0}
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
                                    "typeNames": "ms:mischung", "count": 3000, "startIndex": start,
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
            code = int(f["properties"].get("mischungsg") or -1)
        except ValueError:
            code = -1
        if code in TG_SHARE and f.get("geometry"):
            f["properties"] = {"share": TG_SHARE[code], "code": code}
            out.append(f)
    js = {"type": "FeatureCollection", "features": out,
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2056"}}}
    with open(path, "w") as fh:
        json.dump(js, fh)
    return out


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
    gt = (bounds[0], RES, 0, bounds[3], 0, -RES)
    print(f"grid {cols} x {rows} px, {RES} m", flush=True)
    share = np.full((rows, cols), np.nan, np.float32)

    # Switzerland: broadleaf share (fallback for the Thurgau stands without mixture)
    try:
        info = gdal.Info(BAFU, format="json")
        nd = info["bands"][0].get("noDataValue")
        a = warp(BAFU, bounds, cols, rows, gdal.GDT_Float32)
        ok = (a >= 0) & (a <= 100) & np.isfinite(a) & ((a != nd) if nd is not None else True)
        share[ok] = a[ok]
        print(f"BAFU Waldmischungsgrad: {ok.mean() * 100:.1f} % of the area", flush=True)
    except Exception as e:
        print("WARN: BAFU failed:", e, flush=True)

    # Germany: share of broadleaved pixels
    try:
        a = warp(THUENEN, bounds, cols, rows)
        n_tree = boxsum(np.isin(a, TH_CONIFER + TH_BROADLEAF), SHARE_WIN)
        n_broad = boxsum(np.isin(a, TH_BROADLEAF), SHARE_WIN)
        de = (a >= 0) & (n_tree > 0)
        share[de] = 100.0 * n_broad[de] / n_tree[de]
        print(f"Thünen tree species: {de.mean() * 100:.1f} % of the area", flush=True)
    except Exception as e:
        print("WARN: Thünen failed:", e, flush=True)

    # Thurgau: mixture of the stands
    try:
        path = os.path.join(WORK, "thurgau_stands.geojson")
        feats = thurgau(path)
        print(f"Thurgau: {len(feats)} stands with mixture", flush=True)
        if feats:
            merc = os.path.join(WORK, "thurgau_stands_3857.gpkg")
            gdal.VectorTranslate(merc, path, format="GPKG", dstSRS="EPSG:3857", srcSRS="EPSG:2056",
                                 layerName="stands", makeValid=True)
            ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
            ds.SetGeoTransform(gt)
            ds.SetProjection(m.ExportToWkt())
            ds.GetRasterBand(1).Fill(-1)
            gdal.Rasterize(ds, merc, attribute="share", layers=["stands"])
            t = ds.GetRasterBand(1).ReadAsArray()
            share = np.where(t >= 0, t, share)
            print(f"Thurgau stands: {(t >= 0).mean() * 100:.1f} % of the area", flush=True)
    except Exception as e:
        print("WARN: Thurgau failed:", e, flush=True)

    # small gaps: share of the surroundings (inverse distance, up to FILL_DIST pixels away)
    before = np.isfinite(share).sum()
    ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-1)
    band.WriteArray(np.where(np.isfinite(share), share, -1))
    gdal.FillNodata(band, None, FILL_DIST, 0)
    f = band.ReadAsArray()
    share = np.where(f >= 0, f, np.nan)
    print(f"gaps filled: {(np.isfinite(share).sum() - before) * RES * RES / 10000:.0f} ha", flush=True)

    cls = share_classes(share)
    ds = gdal.GetDriverByName("GTiff").Create(OUT, cols, rows, 1, gdal.GDT_Byte, ["TILED=YES", "COMPRESS=DEFLATE"])
    ds.SetGeoTransform(gt)
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
