#!/usr/bin/env python3
"""Downloads a ready-made hillshade tile service for an area and one zoom level and writes it as one grey GeoTIFF
in Web Mercator (tiled, DEFLATE, with overviews). Pixels without data (outside the country, transparent) get the
value 0 (nodata); real hillshade values are kept in 1..255.

Sources (Web Mercator tiles, 256 px):
  swisstopo  swissALTI3D Reliefschattierung monodirektional, © swisstopo (OGD, attribution required)
  basemapde  basemap.de Web Raster Hillshade, © GeoBasis-DE / BKG, CC BY 4.0 (from ATKIS DGM5)

Usage: fetch_hillshade.py <source> <level> <west> <south> <east> <north> <out.tif> [threads]
"""
import io
import math
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from osgeo import gdal
from PIL import Image

gdal.UseExceptions()
SOURCES = {
    "swisstopo": "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissalti3d-reliefschattierung_monodirektional/default/current/3857/{z}/{x}/{y}.png",
    "basemapde": "https://sgx.geodatenzentrum.de/wmts_basemapde_schummerung/tile/1.0.0/de_basemapde_web_raster_hillshade/default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png",
}
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/render-opentopomaps-var)"}
R = 20037508.342789244


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def fetch(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = r.read()
            img = Image.open(io.BytesIO(data))
            if img.mode == "P":
                img = img.convert("RGBA")
            alpha = np.asarray(img.getchannel("A")) if "A" in img.getbands() else None
            grey = np.asarray(img.convert("L"), dtype=np.uint8)
            if grey.shape != (256, 256):
                grey = np.asarray(Image.fromarray(grey).resize((256, 256), Image.BILINEAR))
                if alpha is not None:
                    alpha = np.asarray(Image.fromarray(alpha).resize((256, 256), Image.NEAREST))
            out = np.maximum(grey, 1)
            if alpha is not None:
                out = np.where(alpha > 127, out, 0).astype(np.uint8)
            if not out.any():
                return None
            return out
        except urllib.error.HTTPError as e:
            if e.code in (204, 400, 404):
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    print("WARN: giving up on", url, flush=True)
    return None


def main():
    src = sys.argv[1]
    url = SOURCES[src]
    z = int(sys.argv[2])
    w, s, e, n = (float(v) for v in sys.argv[3:7])
    out = sys.argv[7]
    threads = int(sys.argv[8]) if len(sys.argv) > 8 else 12
    x0, y0 = tile_xy(n, w, z)
    x1, y1 = tile_xy(s, e, z)
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    size = 2 * R / 2 ** z
    print(f"{src} level {z}: {cols} x {rows} tiles = {cols * rows}, {cols * 256} x {rows * 256} px", flush=True)
    ds = gdal.GetDriverByName("GTiff").Create(
        out, cols * 256, rows * 256, 1, gdal.GDT_Byte,
        ["TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256", "COMPRESS=DEFLATE", "PREDICTOR=2", "BIGTIFF=YES"])
    ds.SetGeoTransform((-R + x0 * size, size / 256, 0, R - y0 * size, 0, -size / 256))
    ds.SetProjection("EPSG:3857")
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    empty = np.zeros((256, 256), np.uint8)
    t0, got = time.time(), 0
    with ThreadPoolExecutor(threads) as pool:
        for r in range(rows):
            urls = [url.format(z=z, x=x0 + c, y=y0 + r) for c in range(cols)]
            tiles = list(pool.map(fetch, urls))
            band.WriteArray(np.hstack([t if t is not None else empty for t in tiles]), 0, r * 256)
            got += sum(t is not None for t in tiles)
            if r % 20 == 0 or r == rows - 1:
                print(f"  row {r + 1}/{rows}, {got} tiles with data, {(time.time() - t0) / 60:.1f} min", flush=True)
    ds.FlushCache()
    ds = None
    ds = gdal.Open(out, gdal.GA_Update)
    gdal.SetConfigOption("COMPRESS_OVERVIEW", "DEFLATE")
    ds.BuildOverviews("AVERAGE", [2, 4, 8, 16, 32, 64])
    ds = None
    print(f"done: {got} tiles with data", flush=True)


if __name__ == "__main__":
    main()
