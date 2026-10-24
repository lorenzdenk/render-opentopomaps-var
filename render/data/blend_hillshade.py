#!/usr/bin/env python3
"""Puts the sharp national hillshades (from fetch_hillshade.py) over the 30 m OpenTopoMap hillshade.

Each source is first matched in brightness and contrast to the 30 m hillshade (on land, where both have data), so the
style (grain-merge, opacity) looks the same, only sharper. The sources are listed in priority order: where several
have data, the first one wins (e.g. swisstopo before basemap.de). At the edge of a source's data the hillshade fades
over a few pixels into the next one, so there is no hard seam at the border. Outside all sources the 30 m hillshade
stays.

Usage: blend_hillshade.py <otm_hillshade.tif> <dem_30m.tif> <W> <S> <E> <N> <level> <out.tif> <src1.tif> [<src2.tif> ...]
"""
import sys

import numpy as np
from osgeo import gdal
from PIL import Image, ImageFilter

gdal.UseExceptions()
base, dem = sys.argv[1], sys.argv[2]
W, S, E, N = map(float, sys.argv[3:7])
level = int(sys.argv[7])
out = sys.argv[8]
sources = sys.argv[9:]
R = 20037508.342789244
RES = 2 * R / 2 ** level / 256
STRIP, PAD, FEATHER = 2048, 48, 8


def small(path, alg="average", nodata=None):
    kw = {"srcNodata": nodata, "dstNodata": nodata} if nodata is not None else {}
    ds = gdal.Warp("", path, format="MEM", dstSRS="EPSG:3857", outputBounds=(W, S, E, N), outputBoundsSRS="EPSG:4326",
                   width=2000, height=0, resampleAlg=alg, **kw)
    return ds.GetRasterBand(1).ReadAsArray().astype(np.float64)


# common grid in Web Mercator at the resolution of the tile level
grid = gdal.Warp("/vsimem/grid.vrt", base, format="VRT", dstSRS="EPSG:3857", outputBounds=(W, S, E, N),
                 outputBoundsSRS="EPSG:4326", xRes=RES, yRes=RES, resampleAlg="bilinear")
gt, cols, rows = grid.GetGeoTransform(), grid.RasterXSize, grid.RasterYSize
bounds = (gt[0], gt[3] + rows * gt[5], gt[0] + cols * gt[1], gt[3])
print(f"output {cols} x {rows} px, {RES:.2f} m (level {level})", flush=True)

ref, h = small(base), small(dem)
layers = []
for i, path in enumerate(sources):
    a = small(path, nodata=0)
    ok = (a > 0) & (h > 1)
    if ok.sum() < 500:
        print(f"{path}: almost no data in the area, left out", flush=True)
        continue
    ma, sa = a[ok].mean(), a[ok].std()
    mb, sb = ref[ok].mean(), ref[ok].std()
    k = 2.5
    lo_a, hi_a, lo_b, hi_b = ma - k * sa, ma + k * sa, mb - k * sb, mb + k * sb
    print(f"{path}: {ok.mean() * 100:.0f} % of the area; mean {ma:.1f} sd {sa:.1f} -> mean {mb:.1f} sd {sb:.1f}", flush=True)
    vrt = gdal.Warp(f"/vsimem/src{i}.vrt", path, format="VRT", dstSRS="EPSG:3857", outputBounds=bounds,
                    width=cols, height=rows, resampleAlg="bilinear", srcNodata=0, dstNodata=0)
    layers.append((vrt, (lo_a, hi_a, lo_b, hi_b)))

drv = gdal.GetDriverByName("GTiff")
dst = drv.Create(out, cols, rows, 1, gdal.GDT_Byte,
                 ["TILED=YES", "COMPRESS=JPEG", "JPEG_QUALITY=85", "BIGTIFF=IF_SAFER"])
dst.SetGeoTransform(gt)
dst.SetProjection(grid.GetProjection())
band = dst.GetRasterBand(1)

for y in range(0, rows, STRIP):
    y0, y1 = max(0, y - PAD), min(rows, y + STRIP + PAD)
    acc = grid.GetRasterBand(1).ReadAsArray(0, y0, cols, y1 - y0).astype(np.float32)
    # lowest priority first, so the first source ends up on top
    for vrt, (lo_a, hi_a, lo_b, hi_b) in reversed(layers):
        a = vrt.GetRasterBand(1).ReadAsArray(0, y0, cols, y1 - y0)
        if not a.any():
            continue
        m = np.clip((a.astype(np.float32) - lo_a) / (hi_a - lo_a) * (hi_b - lo_b) + lo_b, 0, 255)
        mask = Image.fromarray(np.where(a > 0, 255, 0).astype(np.uint8))
        w = np.asarray(mask.filter(ImageFilter.GaussianBlur(FEATHER)), np.float32) / 255
        w = np.clip(w * 2 - 1, 0, 1) * (a > 0)   # fade inside the data edge, 0 outside
        acc = acc * (1 - w) + m * w
    band.WriteArray(np.round(acc[y - y0:y - y0 + min(STRIP, rows - y)]).astype(np.uint8), 0, y)
    print(f"  rows {y}-{min(rows, y + STRIP)} of {rows}", flush=True)
dst.FlushCache()
dst = None
print("written", out)
