#!/usr/bin/env python3
"""Probe: Thurgau 'Forstliche Bestandeskarte' WFS - feature types, attributes, value counts in the test area."""
import collections, json, re, sys, urllib.parse, urllib.request
BASE = "https://ows.geo.tg.ch/geofy_access_proxy/forstliche_bestandeskarte"
UA = {"User-Agent": "LoriMaps-render probe"}
def get(q):
    url = BASE + "?" + q
    print("GET", url, flush=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read().decode("utf-8", "replace")
caps = get("service=WFS&version=2.0.0&request=GetCapabilities")
open(sys.argv[1] + "/caps.xml", "w").write(caps)
names = re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", caps)
print("feature types:", names)
fmts = sorted(set(re.findall(r"<ows:Value>([^<]*json[^<]*)</ows:Value>", caps, re.I)))
print("json formats:", fmts)
for n in names:
    try:
        d = get(f"service=WFS&version=2.0.0&request=DescribeFeatureType&typeNames={n}")
        open(sys.argv[1] + f"/describe_{n.replace(':','_')}.xml", "w").write(d)
        print(n, "fields:", re.findall(r'element[^>]*name="([^"]+)"[^>]*type="([^"]+)"', d))
    except Exception as e:
        print(n, "describe failed", e)
    for fmt in (fmts[:1] or ["application/json"]):
        try:
            # test area Mainau-Weinfelden in LV95
            g = get(f"service=WFS&version=2.0.0&request=GetFeature&typeNames={n}&count=3000"
                    f"&bbox=2722000,1265000,2738000,1281000,urn:ogc:def:crs:EPSG::2056&outputFormat={urllib.parse.quote(fmt)}")
            js = json.loads(g)
            feats = js.get("features", [])
            print(n, len(feats), "features")
            if feats:
                print("example properties:", json.dumps(feats[0]["properties"], ensure_ascii=False))
                for k in feats[0]["properties"]:
                    c = collections.Counter(str(f["properties"].get(k)) for f in feats)
                    if len(c) <= 40:
                        print(f"  {k}: {c.most_common()}")
                    else:
                        print(f"  {k}: {len(c)} distinct, e.g. {c.most_common(8)}")
        except Exception as e:
            print(n, "getfeature failed", fmt, e)
