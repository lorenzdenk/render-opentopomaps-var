#!/usr/bin/env python3
"""Probe of the data sources for contours and forest types in the test area (output: logs dir)."""
import io, json, re, sys, urllib.parse, urllib.request, zipfile
OUT = sys.argv[1]
UA = {"User-Agent": "LoriMaps-render probe"}
def get(url, n=None):
    print("GET", url, flush=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        print("  ->", r.status, r.headers.get("Content-Type"), r.headers.get("Content-Length"), flush=True)
        return r.read() if n is None else r.read(n)
def tryit(name, f):
    print(f"\n===== {name}", flush=True)
    try:
        f()
    except Exception as e:
        print("FAILED:", repr(e)[:500], flush=True)

def lgl():
    base = "https://owsproxy.lgl-bw.de/owsproxy/wcs/WCS_INSP_BW_Hoehe_Coverage_DGM1"
    caps = get(base + "?service=WCS&request=GetCapabilities&version=2.0.1").decode("utf-8", "replace")
    open(OUT + "/lgl_caps.xml", "w").write(caps)
    ids = re.findall(r"<wcs:CoverageId>([^<]+)</wcs:CoverageId>", caps)
    print("coverage ids:", ids)
    print("formats:", re.findall(r"<wcs:formatSupported>([^<]+)<", caps))
    if ids:
        d = get(base + f"?service=WCS&request=DescribeCoverage&version=2.0.1&CoverageId={ids[0]}").decode("utf-8", "replace")
        open(OUT + "/lgl_describe.xml", "w").write(d)
        print("describe (start):", d[:1500])
        axis = re.findall(r'axisLabels="([^"]+)"', d)
        srs = re.findall(r'srsName="([^"]+)"', d)
        print("axis:", axis[:2], "srs:", srs[:2])
        # small piece near Allensbach (Bodanrück), EPSG:25832 approx
        for sub in ("&subset=E(506000,507000)&subset=N(5285000,5286000)", "&subset=x(506000,507000)&subset=y(5285000,5286000)"):
            try:
                data = get(base + f"?service=WCS&request=GetCoverage&version=2.0.1&CoverageId={ids[0]}&format=image/tiff" + sub)
                print("  bytes:", len(data), data[:8])
                if data[:2] in (b"II", b"MM"):
                    open(OUT + "/lgl_sample.tif", "wb").write(data)
                    break
                print(data[:600])
            except Exception as e:
                print("  subset failed", e)

def swiss():
    url = ("https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissalti3d/items?"
           "bbox=9.047,47.567,9.253,47.707&limit=100")
    js = json.loads(get(url))
    feats = js["features"]
    print("items:", len(feats), "next:", [l["href"] for l in js.get("links", []) if l.get("rel") == "next"][:1])
    if feats:
        print("first item:", feats[0]["id"], list(feats[0]["assets"].items())[:4])
        yrs = sorted({f["id"].split("_")[1] for f in feats})
        print("years:", yrs)
        ids = sorted(f["id"] for f in feats)
        print("ids e.g.", ids[:3], ids[-3:])

def thuenen():
    for u in ("https://download.geoservice.dlr.de/TREE_SPECIES_DE/files/",
              "https://download.geoservice.dlr.de/TREE_SPECIES_DE/files/readme.txt"):
        try:
            t = get(u).decode("utf-8", "replace")
            open(OUT + "/thuenen_" + ("index.html" if u.endswith("/") else "readme.txt"), "w").write(t)
            print(re.findall(r'href="([^"]+)"', t)[:40] if u.endswith("/") else t[:800])
        except Exception as e:
            print("failed", u, e)

def bafu():
    data = get("https://data.geo.admin.ch/ch.bafu.landesforstinventar-waldmischungsgrad/data.zip")
    z = zipfile.ZipFile(io.BytesIO(data))
    for i in z.infolist()[:30]:
        print("  ", i.filename, i.file_size)
    js = json.loads(get("https://data.geo.admin.ch/api/stac/v0.9/collections/ch.bafu.landesforstinventar-waldmischungsgrad/items?limit=5"))
    for f in js["features"]:
        print("item", f["id"], {k: v["href"] for k, v in f["assets"].items()})

def tg():
    base = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"
    q = ("?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:hauptbaumart&resultType=hits"
         "&bbox=2722000,1265000,2738000,1281000,urn:ogc:def:crs:EPSG::2056")
    print(get(base + q)[:600])
    q2 = ("?service=WFS&version=2.0.0&request=GetFeature&typeNames=ms:hauptbaumart&count=5&startIndex=3000"
          "&bbox=2722000,1265000,2738000,1281000,urn:ogc:def:crs:EPSG::2056&outputFormat=GEOJSON")
    js = json.loads(get(base + q2))
    print("paging startIndex=3000 ->", len(js.get("features", [])), "features")
    caps = open(OUT + "/../tgcaps.xml").read() if False else ""

for name, f in (("LGL WCS DGM1", lgl), ("swissALTI3D STAC", swiss), ("Thuenen tree species", thuenen),
                ("BAFU Waldmischungsgrad", bafu), ("Thurgau WFS paging", tg)):
    tryit(name, f)
