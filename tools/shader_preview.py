#!/usr/bin/env python3
"""Hillshade comparison: downloads small z14 areas of the candidate hillshade services (basemap.de Hillshade and
Combshade, swisstopo swissALTI3D mono- and multidirectional) plus the 30 m Copernicus hillshade as computed by
render.sh (gdaldem, as OpenTopoMap) and writes one PNG per place and one overview sheet.

Usage: shader_preview.py <outdir>
"""
import io
import math
import os
import re
import sys
import time
import urllib.request

import numpy as np
from osgeo import gdal
from PIL import Image, ImageDraw, ImageFont

gdal.UseExceptions()
UA = {"User-Agent": "LoriMaps-render shader preview (+https://github.com/lorenzdenk/render-opentopomaps-var)"}
R = 20037508.342789244
Z = 14
N = 3  # tiles per side

# name, lat, lon
PLACES = [
    ("Feldberg (Schwarzwald)", 47.874, 8.004),
    ("Albtrauf Hohenneuffen", 48.553, 9.413),
    ("Kreuzlingen/Konstanz (Grenze)", 47.650, 9.175),
    ("Thurgau Seerücken", 47.610, 9.000),
    ("Säntis (Alpstein)", 47.249, 9.343),
    ("Lauterbrunnen", 46.593, 7.909),
]

BM = "https://sgx.geodatenzentrum.de/wmts_basemapde_schummerung/tile/1.0.0/{layer}/default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png"
CH_CAPS = "https://wmts.geo.admin.ch/EPSG/3857/1.0.0/WMTSCapabilities.xml"


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def swiss_layers():
    """Finds the swisstopo relief shading layers and their tile URL templates in the WMTS capabilities."""
    xml = get(CH_CAPS)
    out = {}
    if not xml:
        print("WARN: swisstopo capabilities not available")
        return out
    xml = xml.decode("utf-8", "replace")
    for m in re.finditer(r"<Layer>(.*?)</Layer>", xml, re.S):
        block = m.group(1)
        ident = re.search(r"<ows:Identifier>([^<]+)</ows:Identifier>", block)
        if not ident or "reliefschattierung" not in ident.group(1) or "swissalti3d" not in ident.group(1):
            continue
        tmpl = re.search(r'<ResourceURL[^>]*template="([^"]+)"', block)
        tms = re.search(r"<TileMatrixSet>([^<]+)</TileMatrixSet>", block)
        dim = re.search(r"<Dimension>.*?<Default>([^<]+)</Default>", block, re.S)
        if not tmpl:
            continue
        t = tmpl.group(1).replace("{Time}", dim.group(1) if dim else "current")
        t = t.replace("{TileMatrixSet}", tms.group(1) if tms else "3857")
        t = t.replace("{TileMatrix}", "{z}").replace("{TileCol}", "{x}").replace("{TileRow}", "{y}")
        out[ident.group(1)] = t
        print(f"swisstopo layer {ident.group(1)}: {t} (tile matrix set {tms.group(1) if tms else '?'})")
    return out


def mosaic(template, x0, y0):
    img = np.full((N * 256, N * 256), 255, np.uint8)
    have = 0
    for r in range(N):
        for c in range(N):
            data = get(template.format(z=Z, x=x0 + c, y=y0 + r))
            if not data:
                continue
            t = Image.open(io.BytesIO(data))
            if t.mode in ("RGBA", "LA", "P"):
                t = t.convert("RGBA")
                bg = Image.new("RGBA", t.size, (255, 255, 255, 255))
                t = Image.alpha_composite(bg, t)
            img[r * 256:(r + 1) * 256, c * 256:(c + 1) * 256] = np.asarray(t.convert("L").resize((256, 256)))
            have += 1
    return img if have else None


def copernicus(x0, y0):
    """30 m hillshade like render.sh/OpenTopoMap: Copernicus GLO-30 -> Mercator 30 m -> gdaldem hillshade -z 2."""
    size = 2 * R / 2 ** Z
    W, Nn = -R + x0 * size, R - y0 * size
    E, S = W + N * size, Nn - N * size
    lon_w, lon_e = W / R * 180, E / R * 180
    lat = lambda yy: math.degrees(math.atan(math.sinh(yy / R * math.pi)))
    lat_s, lat_n = lat(S), lat(Nn)
    srcs = []
    for la in range(math.floor(lat_s), math.floor(lat_n) + 1):
        for lo in range(math.floor(lon_w), math.floor(lon_e) + 1):
            name = f"Copernicus_DSM_COG_10_N{la:02d}_00_E{lo:03d}_00_DEM"
            srcs.append(f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif")
    try:
        warp = gdal.Warp("/vsimem/w.tif", srcs, dstSRS="EPSG:3857", outputBounds=(W - 300, S - 300, E + 300, Nn + 300),
                         xRes=30, yRes=30, resampleAlg="bilinear")
        gdal.DEMProcessing("/vsimem/h.tif", warp, "hillshade", zFactor=2, computeEdges=True)
        out = gdal.Warp("", "/vsimem/h.tif", format="MEM", outputBounds=(W, S, E, Nn), width=N * 256, height=N * 256,
                        resampleAlg="bilinear")
        return out.GetRasterBand(1).ReadAsArray().astype(np.uint8)
    except Exception as e:
        print("WARN: Copernicus failed:", e)
        return None


def font(sz):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    variants = [("OTM bisher (Copernicus 30 m)", None),
                ("basemap.de Hillshade", BM.format(layer="de_basemapde_web_raster_hillshade", z="{z}", x="{x}", y="{y}")),
                ("basemap.de Combshade", BM.format(layer="de_basemapde_web_raster_combshade", z="{z}", x="{x}", y="{y}"))]
    for ident, t in sorted(swiss_layers().items()):
        label = "swisstopo " + ("monodirektional" if "mono" in ident else "multidirektional" if "multi" in ident else ident)
        variants.append((label, t))
    f_title, f_lab = font(26), font(20)
    sheets = []
    for name, la, lo in PLACES:
        fx, fy = tile_xy(la, lo, Z)
        x0, y0 = int(fx) - N // 2, int(fy) - N // 2
        panels = []
        for label, t in variants:
            a = copernicus(x0, y0) if t is None else mosaic(t, x0, y0)
            print(f"{name}: {label}: {'ok' if a is not None else 'no data'}", flush=True)
            if a is None:
                a = np.full((N * 256, N * 256), 235, np.uint8)
                label += " – keine Daten"
            im = Image.fromarray(a).convert("RGB")
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, im.width, 30], fill=(255, 255, 255))
            d.text((8, 4), label, fill=(0, 0, 0), font=f_lab)
            panels.append(im)
        w = N * 256
        sheet = Image.new("RGB", (len(panels) * (w + 10) - 10, w + 44), (255, 255, 255))
        ImageDraw.Draw(sheet).text((6, 6), f"{name}  (z{Z}, {la:.3f}, {lo:.3f})", fill=(0, 0, 0), font=f_title)
        for i, p in enumerate(panels):
            sheet.paste(p, (i * (w + 10), 44))
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        sheet.save(os.path.join(out, f"{slug}.png"))
        # per-variant crops for viewing on a phone
        for i, p in enumerate(panels):
            vs = re.sub(r"[^a-z0-9]+", "-", variants[i][0].lower()).strip("-")
            p.save(os.path.join(out, f"{slug}__{vs}.jpg"), quality=88)
        sheets.append(sheet)
    W = max(s.width for s in sheets)
    allsheet = Image.new("RGB", (W, sum(s.height + 20 for s in sheets)), (255, 255, 255))
    y = 0
    for s in sheets:
        allsheet.paste(s, (0, y))
        y += s.height + 20
    allsheet.thumbnail((W // 2, 100000))
    allsheet.save(os.path.join(out, "uebersicht.jpg"), quality=88)
    print("done")


if __name__ == "__main__":
    main()
