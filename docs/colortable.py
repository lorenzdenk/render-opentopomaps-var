from PIL import Image, ImageDraw, ImageFont
SYM = "otm/mapnik/symbols-otm/"
F = "/usr/share/fonts/truetype/dejavu/"
fb = ImageFont.truetype(F + "DejaVuSans-Bold.ttf", 26)
fn = ImageFont.truetype(F + "DejaVuSans.ttf", 22)
fs = ImageFont.truetype(F + "DejaVuSans.ttf", 19)
fm = ImageFont.truetype(F + "DejaVuSansMono.ttf", 20)
BASE = (255, 255, 255)

# (name, zoom, layers: list of ("fill", hex, opacity) or ("pattern", file, opacity), description)
rows = [
    ("Wald (forest / wood)", "ab 11", [("fill", "#b7d97b", 1), ("pattern", "forest.png", 1)], "#b7d97b + Baumsymbole"),
    ("Wald, Nadel", "ab 12", [("pattern", "forest-coniferous.png", 1)], "#b7d97b + Nadelbaum-Symbole"),
    ("Wald, Laub", "ab 12", [("pattern", "forest-deciduous.png", 1)], "#b7d97b + Laubbaum-Symbole"),
    ("Wald über Schummerung", "ab 11", [("fill", "#ffffd9", 0.5)], "#ffffd9, 50 %, soft-light"),
    ("Waldrand", "ab 14", [("fill", "#1c9e1f", 1)], "Linie #1c9e1f"),
    ("Wald, Zoom 9–10", "9–10", [("fill", "#b9d984", 1)], "#b9d984"),
    ("Wiese, Grasland", "ab 13", [("pattern", "meadow.png", 1)], "Symbole #25b733"),
    ("Gebüsch (scrub)", "ab 13", [("fill", "#bfd4a9", 0.2), ("pattern", "scrub.png", 1)], "#bfd4a9 20 % + Symbole"),
    ("Rebberg", "ab 13", [("pattern", "vineyard.png", 1)], "Symbole #25b733"),
    ("Obstgarten", "ab 13", [("pattern", "orchard.png", 1)], "Symbole #25b733"),
    ("Fell", "ab 13", [("pattern", "fell.png", 1)], "Symbole #a1bf27"),
    ("Fels (bare_rock)", "ab 12", [("pattern", "bare_rock.png", 0.7)], "Muster #979593"),
    ("Geröll (scree)", "ab 10", [("pattern", "scree.png", 1)], "Punktmuster"),
    ("Sand, Strand", "ab 12", [("pattern", "sand.png", 0.7)], "#fff4a9"),
    ("Sumpf (swamp)", "ab 10", [("fill", "#73b64b", 0.3), ("pattern", "wetland.png", 1)], "#73b64b 30 % + Sumpfzeichen"),
    ("Moor (bog)", "ab 10", [("fill", "#d9cf57", 0.2), ("pattern", "wetland.png", 1)], "#d9cf57 20 % + Sumpfzeichen"),
    ("Feuchtgebiet sonst", "ab 10", [("fill", "#304eff", 0.1), ("pattern", "wetland.png", 1)], "#304eff 10 % + Sumpfzeichen"),
    ("Röhricht", "ab 11", [("pattern", "reedbed.png", 1)], "Muster"),
    ("Watt", "ab 9", [("pattern", "tidalflat.png", 0.7)], "Muster"),
    ("Gletscher", "ab 9", [("fill", "#d0f8ff", 0.5)], "#d0f8ff 50 %"),
    ("Seen, Flüsse, Meer", "ab 11", [("fill", "#a3dde8", 1)], "#a3dde8"),
    ("Wasser, Zoom 0–10", "0–10", [("fill", "#97d2e3", 1)], "#97d2e3"),
    ("Siedlung, Industrie, Schule", "10–13", [("fill", "#aaaaaa", 0.3)], "#aaaaaa 30 % (Zoom 14: 15 %, ab 15: 10 %)"),
    ("Park", "ab 13", [("fill", "#c1dfac", 0.5)], "#c1dfac 50 %"),
    ("Sportplatz", "ab 16", [("fill", "#b6dea4", 0.5)], "#b6dea4 50 %"),
    ("Gebäude", "13 / 14 / 15+", [("fill", "#777777", 1)], "#777777 → schwarz → #555555"),
    ("Flugplatz-Flächen", "ab 12", [("fill", "#dddddd", 1)], "#dddddd"),
    ("Militär", "ab 9", [("pattern", "military_area_z12.png", 1)], "rotes Schraffurmuster"),
    ("Heide (heath)", "–", [], "wird nicht gezeichnet (bleibt weiss)"),
]

def hexrgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

SW, SH, RH = 170, 64, 76
W = 1100
img = Image.new("RGB", (W, 120 + RH * len(rows) + 60), "white")
d = ImageDraw.Draw(img)
d.text((24, 22), "OpenTopoMap – Flächen und Farben", font=fb, fill="black")
d.text((24, 62), "Muster so dargestellt, wie sie auf weissem Grund erscheinen (ohne Schummerung)", font=fs, fill=(90, 90, 90))
y = 110
for name, zoom, layers, desc in rows:
    sw = Image.new("RGBA", (SW, SH), BASE + (255,))
    for kind, val, op in layers:
        if kind == "fill":
            ov = Image.new("RGBA", (SW, SH), hexrgb(val) + (int(255 * op),))
        else:
            tile = Image.open(SYM + val).convert("RGBA")
            ov = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
            # patterns are drawn at map scale 2 (512 px tiles) -> enlarge x2 for a realistic look
            tile = tile.resize((tile.width * 2, tile.height * 2), Image.NEAREST)
            for tx in range(0, SW, tile.width):
                for ty in range(0, SH, tile.height):
                    ov.alpha_composite(tile, (tx, ty))
            if op < 1:
                a = ov.getchannel("A").point(lambda v: int(v * op)); ov.putalpha(a)
        sw.alpha_composite(ov)
    if name.startswith("Waldrand"):
        sw = Image.new("RGBA", (SW, SH), BASE + (255,)); ImageDraw.Draw(sw).line([(10, SH // 2), (SW - 10, SH // 2)], fill=(28, 158, 31), width=4)
    img.paste(sw.convert("RGB"), (24, y))
    d.rectangle([24, y, 24 + SW, y + SH], outline=(170, 170, 170))
    d.text((24 + SW + 22, y + 6), name, font=fn, fill="black")
    d.text((24 + SW + 22, y + 36), desc, font=fm, fill=(70, 70, 70))
    d.text((W - 24, y + 6), zoom, font=fs, fill=(90, 90, 90), anchor="ra")
    y += RH
img.save("otm-farben.png")
print(img.size)
