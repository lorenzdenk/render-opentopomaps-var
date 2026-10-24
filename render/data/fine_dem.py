#!/usr/bin/env python3
"""Fine elevation model for the contour lines (Germany / Switzerland):

  Switzerland: swissALTI3D, 2 m (© swisstopo), tiles from the STAC API of data.geo.admin.ch
  Baden-Württemberg: DGM1 of the LGL (dl-de/by-2-0, "LGL, www.lgl-bw.de"), INSPIRE WCS, read at 2 m
  elsewhere: the 30 m Copernicus DEM of render.sh (warp-30.tif)

All are put on one Web Mercator grid (RES m), swissALTI3D before the DGM1 before Copernicus, with a soft
transition at the edges of each source, and smoothed a little (Gaussian, SIGMA pixels), so the 10 m contour
lines follow the terrain without the noise of single trees, walls and ditches.

Usage: fine_dem.py <W> <S> <E> <N> <copernicus.tif or -> <out.tif> [workdir]
  "-" reads the Copernicus GLO-30 tiles directly from AWS (for preparing before render.sh has its DEM).
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from osgeo import gdal, osr
from PIL import Image, ImageFilter

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
W, S, E, N = map(float, sys.argv[1:5])
COP, OUT = sys.argv[5], sys.argv[6]
WORK = sys.argv[7] if len(sys.argv) > 7 else os.path.dirname(os.path.abspath(OUT))
RES = float(os.environ.get("FINE_DEM_RES", "6"))       # metres in Web Mercator (about 4 m on the ground here)
SIGMA = float(os.environ.get("FINE_DEM_SIGMA", "1.5"))  # pixels
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/render-opentopomaps-var)"}
STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissalti3d/items"
WCS = "https://owsproxy.lgl-bw.de/owsproxy/wcs/WCS_INSP_BW_Hoehe_Coverage_DGM1"


def get(url, path=None, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                data = r.read()
            if path:
                with open(path + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(path + ".tmp", path)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                print("  not available:", url, e.code, flush=True)
                return None
            time.sleep(3 * (i + 1))
        except Exception as e:
            print("  retry", url, repr(e)[:120], flush=True)
            time.sleep(3 * (i + 1))
    print("WARN: giving up", url, flush=True)
    return None


def swiss_tiles(d):
    """swissALTI3D 2 m tiles touching the area (newest year per tile)."""
    os.makedirs(d, exist_ok=True)
    url = STAC + "?" + urllib.parse.urlencode({"bbox": f"{W},{S},{E},{N}", "limit": 100})
    best = {}
    while url:
        js = json.loads(get(url))
        for f in js["features"]:
            _, year, key = f["id"].split("_")
            for name, a in f["assets"].items():
                if name.endswith(".tif") and a.get("eo:gsd") == 2.0:
                    if key not in best or year > best[key][0]:
                        best[key] = (year, a["href"])
        url = next((l["href"] for l in js.get("links", []) if l.get("rel") == "next"), None)
    print(f"swissALTI3D: {len(best)} tiles of 1 km", flush=True)
    jobs = [(href, os.path.join(d, os.path.basename(href))) for _, href in best.values()]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda j: os.path.exists(j[1]) or get(j[0], j[1]), jobs))
    return [p for _, p in jobs if os.path.exists(p)]


def lgl_tiles(d):
    """DGM1 of Baden-Württemberg from the WCS in 2 km pieces (EPSG:25832), only where the area lies in BW."""
    os.makedirs(d, exist_ok=True)
    src, dst = osr.SpatialReference(), osr.SpatialReference()
    src.ImportFromEPSG(4326), dst.ImportFromEPSG(25832)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    t = osr.CoordinateTransformation(src, dst)
    pts = [t.TransformPoint(x, y)[:2] for x in (W, E) for y in (S, N)]
    x0 = math.floor(min(p[0] for p in pts) / 2000) * 2000
    x1 = math.ceil(max(p[0] for p in pts) / 2000) * 2000
    y0 = math.floor(min(p[1] for p in pts) / 2000) * 2000
    y1 = math.ceil(max(p[1] for p in pts) / 2000) * 2000
    # coverage of the service (EPSG:25832)
    x0, y0, x1, y1 = max(x0, 388000), max(y0, 5264000), min(x1, 611000), min(y1, 5520000)
    jobs = []
    for x in range(int(x0), int(x1), 2000):
        for y in range(int(y0), int(y1), 2000):
            p = os.path.join(d, f"dgm1_{x}_{y}.tif")
            q = urllib.parse.urlencode({"service": "WCS", "request": "GetCoverage", "version": "2.0.1",
                                        "CoverageId": "EL.ElevationGridCoverage", "format": "image/tiff"})
            jobs.append((f"{WCS}?{q}&subset=E({x},{x + 2000})&subset=N({y},{y + 2000})", p))
    print(f"LGL DGM1: {len(jobs)} pieces of 2 km", flush=True)

    def one(j):
        if os.path.exists(j[1]):
            return
        data = get(j[0], j[1])
        if data is not None and data[:2] not in (b"II", b"MM"):
            print("  not a GeoTIFF:", j[0], data[:200], flush=True)
            os.remove(j[1])
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(one, jobs))
    out = []
    for _, p in jobs:
        if not os.path.exists(p):
            continue
        ds = gdal.Open(p)
        b = ds.GetRasterBand(1)
        a = b.ReadAsArray(0, 0, ds.RasterXSize, ds.RasterYSize, buf_xsize=64, buf_ysize=64)
        nd = b.GetNoDataValue()
        valid = np.isfinite(a) & (a > 50) & (a < 5000) & ((a != nd) if nd is not None else True)
        if valid.any():
            out.append(p)
    print(f"LGL DGM1: {len(out)} pieces with data", flush=True)
    return out


def to_grid(files, srs, bounds, cols, rows, alg):
    if not files:
        return None
    vrt = files[0] if len(files) == 1 and isinstance(files[0], gdal.Dataset) else gdal.BuildVRT("", files)
    ds = gdal.Warp("", vrt, format="MEM", dstSRS="EPSG:3857", outputBounds=bounds, width=cols, height=rows,
                   resampleAlg=alg, dstNodata=-32768, outputType=gdal.GDT_Float32)
    a = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    # nodata of the sources (various values) and areas outside them: nothing here lies below 50 m
    a[(a < 50) | (a > 5000) | ~np.isfinite(a)] = np.nan
    return a


def weight(valid, px):
    m = Image.fromarray(np.where(valid, 255, 0).astype(np.uint8))
    w = np.asarray(m.filter(ImageFilter.GaussianBlur(px)), np.float32) / 255
    return np.clip(w * 2 - 1, 0, 1) * valid


def gauss(a, s):
    r = int(3 * s + 0.5)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()
    p = np.pad(a, r, mode="edge")
    p = sum(k[i] * p[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    return sum(k[i] * p[i:i + a.shape[0], :] for i in range(2 * r + 1)).astype(np.float32)


def copernicus_vrt():
    srcs = []
    for la in range(math.floor(S), math.floor(N) + 1):
        for lo in range(math.floor(W), math.floor(E) + 1):
            n = f"Copernicus_DSM_COG_10_{'N' if la >= 0 else 'S'}{abs(la):02d}_00_{'E' if lo >= 0 else 'W'}{abs(lo):03d}_00_DEM"
            srcs.append(f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif")
    vrt = gdal.BuildVRT("/vsimem/cop.vrt", srcs)
    vrt.FlushCache()
    return vrt


def main():
    global COP
    t0 = time.time()
    if COP == "-":
        COP = copernicus_vrt()
    grid = gdal.Warp("", COP, format="VRT", dstSRS="EPSG:3857", outputBounds=(W, S, E, N), outputBoundsSRS="EPSG:4326",
                     xRes=RES, yRes=RES)
    gt, cols, rows = grid.GetGeoTransform(), grid.RasterXSize, grid.RasterYSize
    bounds = (gt[0], gt[3] + rows * gt[5], gt[0] + cols * gt[1], gt[3])
    print(f"grid {cols} x {rows} px, {RES} m", flush=True)
    dem = to_grid([COP], 3857, bounds, cols, rows, "bilinear")
    dem = np.where(np.isnan(dem), np.nanmedian(dem) if np.isfinite(dem).any() else 0, dem)
    used = []
    for name, files, srs in (("LGL DGM1", lgl_tiles(os.path.join(WORK, "dgm1")), 25832),
                             ("swissALTI3D", swiss_tiles(os.path.join(WORK, "swissalti3d")), 2056)):
        a = to_grid(files, srs, bounds, cols, rows, "average")
        if a is None:
            print(f"{name}: no data", flush=True)
            continue
        valid = ~np.isnan(a)
        if not valid.any():
            continue
        diff = (a - dem)[valid]
        print(f"{name}: {valid.mean() * 100:.0f} % of the area, median difference to the lower layer {np.median(diff):+.1f} m",
              flush=True)
        w = weight(valid, 12)
        dem = dem * (1 - w) + np.where(valid, a, 0) * w
        used.append(name)
    dem = gauss(dem, SIGMA)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(OUT, cols, rows, 1, gdal.GDT_Float32, ["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3", "BIGTIFF=IF_SAFER"])
    ds.SetGeoTransform(gt)
    ds.SetProjection(grid.GetProjection())
    ds.GetRasterBand(1).WriteArray(dem)
    ds = None
    print(f"written {OUT} ({', '.join(used) or 'Copernicus only'}), {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
