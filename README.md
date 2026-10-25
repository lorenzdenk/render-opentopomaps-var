# render-opentopomaps-var – OpenTopoMap für Deutschland (BW) und die Schweiz

Fork von [lorimaps-render](https://github.com/lorenzdenk/lorimaps-render): gleicher Ablauf und Stil, aber mit
scharfer amtlicher Schummerung statt der 30-m-Schummerung aus dem Copernicus-DEM:

- **Schweiz:** swisstopo swissALTI3D Reliefschattierung monodirektional (© swisstopo, OGD)
- **Deutschland:** basemap.de Web Raster Hillshade aus dem ATKIS-DGM5 (© GeoBasis-DE / BKG, CC BY 4.0)

In der Regionsdatei: `HILLSHADE_SOURCES="swisstopo basemapde"` (Reihenfolge = Vorrang; wo beide Daten haben, gilt
swisstopo) und `HILLSHADE_LEVEL=14` (Kachelstufe der Dienste, ~6,5 m). `render/data/fetch_hillshade.py` lädt die
Kacheln als GeoTIFF (zwischengespeichert im Release `hillshade-data`), `render/data/blend_hillshade.py` passt jede Quelle
an die Helligkeit der OTM-Schummerung an und legt sie mit weichem Übergang über die 30-m-Schummerung. Ausserhalb
beider Länder bleibt die 30-m-Schummerung. `tools/shader_preview.py` (Workflow „Hillshade preview“) vergleicht die
Varianten an einigen Orten (Branch `shader-preview`).

**Höhenlinien** (`FINE_DEM=1`): aus swissALTI3D 2 m (Schweiz, STAC von data.geo.admin.ch) und dem DGM1 des LGL
(Baden-Württemberg, INSPIRE-WCS, dl-de/by-2-0), auf 6 m zusammengesetzt und leicht geglättet
(`render/data/fine_dem.py`); ausserhalb bleibt Copernicus 30 m.

**Waldtypen** (`FOREST_TYPES=1`): OSM-Wald eingefärbt nach Laubholzanteil in vier Stufen, Kiefer und Birke
gesondert, wo sie dominieren (`render/forest/`). Schweiz: Laubholzanteil aus dem BAFU-Waldmischungsgrad
(Sentinel-1/2, 2023, 10 m), Kiefer aus der forstlichen Bestandeskarte Thurgau (Hauptbaumart Föhre; Birke hat dort
keine eigene Klasse). Deutschland: Baumartenkarte 2022 von DLR/Thünen (10 m, CC BY 4.0), Laubholzanteil als Anteil
der Laubholz-Pixel im Umkreis von ~55 m, Kiefer, Birke und Kahlflächen als häufigste Klasse im Umkreis von ~35 m.
Farben (`FOREST_COLOURS` in `customize_style.py`): Nadelwald 0–10 % #6E9F80, Misch nadelholzreich 10–50 % #84AE78,
Misch laubholzreich 50–90 % #92BF66, Laubwald 90–100 % #9CCB55, Kiefer #B5B08A, Birke #E2DC7E,
ohne Angabe #BEDB96, Kahlfläche #E6E0C6. Vorbereitete Raster liegen im Release `prepared-data`.

Testregion: `regions/mainau-weinfelden.env` (Quadrat Insel Mainau – Weinfelden, bis z17).

---

# LoriMaps-Render – eigene OpenTopoMap-Karten als MBTiles

> **GitHub:** Jeder Push, der etwas in `render/` ändert, startet das Rendern (Workflow „Render OpenTopoMap MBTiles“).
> Die fertige Karte erscheint unter *Releases* (`map-N`), Logs und Beispielkacheln im Branch `render-logs`.
> Die Skripte liegen hier im Ordner `render/` (im Laptop-Paket direkt im Hauptordner).

Dieses Paket erzeugt Rasterkarten im OpenTopoMap-Stil (mit eigenen Anpassungen für Tasmanien) als
**MBTiles-Datei** für die App LoriMaps: 512-px-Kacheln, WebP, identische Kacheln nur einmal gespeichert.

Alles läuft auf **Ubuntu 24.04**: direkt unter Linux, unter Windows mit **WSL2** oder überall mit **Docker**.

---

## 1. Inhalt

| Datei | Zweck |
|---|---|
| `render.sh` | Hauptskript: Software, Daten, Datenbank, Höhenmodell, Vorverarbeitung, Rendern |
| `region.env` | **Einstellungen**: welche Region, Vorschau oder Kacheln, Schrift, Format |
| `regions/*.env` | Regionen: Name, Begrenzungsrechteck, Zoomstufen, OSM-Quelle |
| `customize_style.py` | eigene Änderungen am OpenTopoMap-Stil (siehe Abschnitt 5) |
| `symbols/*.svg` | eigene Symbole (Zeltplatz, verschlossenes Tor) |
| `render_tiles.py` | rendert die Kacheln parallel in eine MBTiles-Datei (WebP/PNG, Deduplizierung) |
| `render_preview.py` | Vorschaubilder einzelner Orte, Schriftvergleiche, setzt die Kartenschrift |
| `preview_places.txt` | feste Vorschau-Orte (Name; Breite; Länge; Zoom) |
| `merge_mbtiles.py` | fügt Teildateien (Shards) zu einer MBTiles-Datei zusammen |
| `push_logs.sh` | nur für GitHub Actions: Logs auf einen Branch schreiben |
| `github-workflow/render-otm.yml` | der bisherige GitHub-Workflow (8 parallele Rechner), falls man ihn wieder braucht: nach `.github/workflows/` eines (privaten) Repos, die Skripte dort in den Ordner `render/` |
| `docker/Dockerfile` | fertige Ubuntu-Umgebung für Docker |
| `docs/otm-farben.png`, `docs/colortable.py` | Farbtabelle der OpenTopoMap-Flächen (Vorbereitung TASVEG) |

---

## 2. Einrichten

### Variante A: Ubuntu 24.04 oder WSL2 (Windows) – empfohlen

Windows: In PowerShell (als Administrator) `wsl --install -d Ubuntu-24.04`, neu starten, Benutzer anlegen.
Danach in Ubuntu:

```bash
sudo apt update && sudo apt install -y git curl unzip
unzip lorimaps-render.zip -d ~ && cd ~/lorimaps-render
bash render.sh            # beim ersten Mal wird alle Software installiert (sudo-Passwort)
```

Unter WSL den Ordner **im Linux-Dateisystem** (`~/…`) lassen, nicht unter `/mnt/c/…` – sonst ist alles
um ein Vielfaches langsamer. Die fertige Karte liegt in `~/work/out/` und ist in Windows unter
`\\wsl$\Ubuntu-24.04\home\<name>\work\out` erreichbar.

WSL nimmt sich standardmässig nur die Hälfte des Arbeitsspeichers. Für ganz Tasmanien sind 8 GB gut;
bei Bedarf in `C:\Users\<name>\.wslconfig`:

```ini
[wsl2]
memory=12GB
```

### Variante B: Docker (Windows, macOS, Linux)

```bash
cd lorimaps-render
docker build -t lorimaps-render docker
docker run --rm -it \
  -v "$PWD":/home/render/lorimaps-render \
  -v lorimaps-work:/work -v lorimaps-pg:/var/lib/postgresql \
  -v "$PWD/out":/out \
  lorimaps-render
```

Die Volumes `lorimaps-work` und `lorimaps-pg` behalten Datenbank und Höhenmodell zwischen den Läufen
(wichtig für `SKIP_DATA=1`). Die Karte landet im Ordner `out/` neben den Skripten.
Optionen werden mit `-e`, z.B. `-e SKIP_DATA=1`, übergeben.

### Platz und Speicher

- Tasmanien: etwa 15–20 GB freier Platz (Australien-PBF ~ 1 GB, Datenbank, Höhenmodell, Höhenlinien).
- 8 GB RAM reichen, 16 GB sind angenehmer.

---

## 3. Benutzen

### Region wählen

In `region.env` die Zeile `REGIONS="tasmania"` anpassen (mehrere: `REGIONS="huonville kreuzlingen"`).
Neue Region: eine Datei in `regions/` kopieren und anpassen:

```bash
NAME=huon-hartz                      # Dateiname: huon-hartz-otm.mbtiles
TITLE="Huonville – Hartz Mountains"  # Name in der App
BBOX=146.700,-43.280,147.080,-42.995 # West, Süd, Ost, Nord (Grad)
MINZOOM=0
MAXZOOM=16
EARLY_TRAILS=2                       # Pfade/Wege 2 Stufen früher (dünn besiedelte Gebiete); 0 = wie OTM
PBF_URLS="https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf"
```

Das Rechteck findet man z.B. auf https://boundingbox.klokantech.com (Format „CSV“).
Für die Schweiz: `https://download.geofabrik.de/europe/switzerland-latest.osm.pbf`; mehrere URLs
mit Leerzeichen getrennt werden zusammengeführt (z.B. Thurgau = Schweiz + Baden-Württemberg-Teile).

### Vorschau oder Karte

- `MODE=preview` – nur einige Bilder (in `out/preview/`), schnell, zum Ausprobieren von Stiländerungen.
  Orte aus `preview_places.txt`, und automatisch gesuchte Beispiele: `Aussichtspunkt`, `Zeltplatz`,
  `Tor_verschlossen`, `Pisten`, `Pisten_4WD`, `Pfad_unsichtbar`, `Weg_privat`. Auswahl mit `PREVIEW_PLACES`.
- `MODE=tiles` – die ganze MBTiles-Datei.

### Schneller wiederholen

```bash
SKIP_APT=1 SKIP_DATA=1 bash render.sh
```

`SKIP_DATA=1` überspringt Download, Import, Höhenmodell und Vorverarbeitung und rendert nur mit dem
neu gepatchten Stil – ideal, um am Stil zu feilen (TASVEG!). Geht nur, wenn der letzte volle Lauf
**dieselbe Region** hatte (oder eine grössere, die die neue enthält).

### Weitere Einstellungen in `region.env`

- `FONT=trebuchet` – Kartenschrift (dejavu, noto, roboto, opensans, verdana, trebuchet, tahoma,
  helvetica, geometric, swiss). Mit `MODE=preview` und mehreren `PREVIEW_FONTS` gibt es Vergleichsbilder.
- `TILE_FORMAT=webp:85` – WebP mit Qualität 85 (etwa 40 % kleiner als PNG); `png8:m=h` = PNG 256 Farben.
- `SCALE=2` – 512-px-Kacheln (scharf auf dem Handy). LoriMaps erkennt die Kachelgrösse selbst.
- `MAGNIFY=2` – Linien, Symbole und Schrift doppelt so gross, gestochen scharf. Jede Zoomstufe zeigt dann
  den Inhalt der nächstkleineren Stufe (z14 sieht aus wie z13 vergrössert); für dieselben Details deshalb eine
  Zoomstufe mehr rendern (z.B. bis 17 statt 16). `MAGNIFY=1` = wie OpenTopoMap. Auch pro Region setzbar.
- `GITHUB_SHARDS=8` – Anzahl paralleler GitHub-Rechner (gratis höchstens 20 gleichzeitig; jeder braucht
  ~10 min Vorbereitung, für kleine Gebiete also wenige nehmen). Auch pro Region setzbar.

### Karte aufs Handy

Datei `…-otm.mbtiles` aufs Handy kopieren (USB, Cloud), in LoriMaps: Kartenmenü → „+ Karte hinzufügen“.

---

## 4. Ablauf von `render.sh`

1. **Software** per apt: PostgreSQL 16 + PostGIS, osm2pgsql, osmium, GDAL, Mapnik (python3-mapnik), Schriften
   (inkl. Microsoft-Kernschriften für Trebuchet MS).
2. **Stil**: frischer Klon von https://github.com/der-stefan/OpenTopoMap, dann `customize_style.py`.
3. **Datenbank** `gis` (OSM) und `contours` (Höhenlinien). PostgreSQL wird auf Tempo eingestellt
   (`fsync=off` usw.) – die Datenbank ist nur ein Zwischenprodukt.
4. **OSM-Daten**: Geofabrik-Auszug laden, mit `osmium extract` auf das Rechteck (+0,05° Rand) zuschneiden,
   mit osm2pgsql und OTMs `opentopomap.style` importieren.
5. **Höhenmodell**: Copernicus GLO-30 (30 m) von AWS, Kachelnamen wie
   `Copernicus_DSM_COG_10_S43_00_E146_00_DEM`. Daraus Mercator-Raster in 5000/1000/700/500/90/30 m,
   Farbrelief, Schummerungen, **Übersichten (gdaladdo)** und Höhenlinien alle 10 m.
6. **Wasserflächen** (Meer) von osmdata.openstreetmap.de, auf das Gebiet zugeschnitten.
7. **OTM-Vorverarbeitung**: Flächenbeschriftungen, Tabellen für kleine Zoomstufen, Sättel,
   Gipfel-Dominanz (Suchradius auf 25 km verkleinert), Parkplätze, Aussichtspunkt-Richtungen.
8. **Rendern** mit Mapnik (`scale_factor` 2 → 512 px), WebP über Pillow, in MBTiles.

---

## 5. Eigene Stiländerungen (`customize_style.py`)

Jeder Patch prüft, dass der Originaltext noch existiert – ändert OTM etwas, bricht das Skript mit einer
klaren Meldung ab, statt still nichts zu tun.

- **Aussichtspunkte** auch ohne `direction`-Tag (Rundum-Symbol), nie von Beschriftungen verdeckt.
- **Tracks** schwarz wie OTM, Tracktypen deutlicher:

  | | grade2 | grade3 | grade4 | grade5 |
  |---|---|---|---|---|
  | z14 | 1.4 | 0.5 | 0.5, Strich 1.8/1.8 | 0.6, Strich 3/6 |
  | z15–17 | 2.0 | 0.9 | 0.9, Strich 2.4/2.4 | 0.9, Strich 4/8 |

  grade1 unverändert. Unbekannter Tracktyp wird wie OTM gezeichnet.
- **„4WD“** als brauner Text neben Tracks mit `4wd_only=yes` oder `smoothness` very_bad und schlechter.
- **Unsichtbar / kein Zutritt**: Pfade und Tracks mit `trail_visibility=no/horrible` oder
  `access=no/private` (ohne Fussgänger-Freigabe) hellgrau `#b4b4b4`, sonst keine Markierung.
- **Zeltplätze**: grünes Symbol ab z11, ab z13 gross mit grünem fettem Namen.
- **Verschlossene Tore/Schranken** (`locked=yes`): rote „Durchfahrt verboten“-Scheibe ab z13.
- **Namen von Pfaden, Tracks und Nebenstrassen** (tertiary, unclassified, residential, service …) ab z14 (mit `EARLY_TRAILS=2` ab z13), bei langen Wegen mehrfach wiederholt.
- **Pfade** auch auf z14 und früher gepunktet (wie OTM ab z15), nicht gestrichelt.
- **Wald** nur grün, ohne Baumsymbole.
- **Schutzgebietsgrenzen** mit feinen grauen Rändern am grünen Band; Höhenzahlen ohne hellen Hintergrund;
  einzelne markante Bäume (OSM) ab z12.
- **Öffentliche Parkplätze** ab z14.
- **`EARLY_TRAILS=2`**: Pfade und Tracks erscheinen zwei Zoomstufen früher (z12 statt z14,
  Tracks grade1/2 ab z11), leicht dünner.
- **TASVEG** (`TASVEG=1` in der Region, nur Tasmanien): Vegetation aus TASVEG 5.0 statt OSM-Wald/-Gebüsch,
  Einteilung A „Waldgefühl“ aus `render/tasveg/klassen_waldtypen.csv`:
  1 Regenwald `#4F9A57`, 2 Nasswald über Regenwald `#82BC6A`, 3 übriger Nasswald `#B6D778`,
  4 trockener Eukalyptuswald `#D6C468`, 5 sonstiger Wald/Sumpfwald `#9DBF57`, 6 Offenland/Hochland `#EDE8D2`,
  Kulturland `#F4F0E6`, Plantagen `#DCDDC6`; Siedlungen und O-Codes (Wasser, Sand, Fels) bleiben OpenTopoMap. Lichter Wald (`FOREST_STR=Woodland`)
  fein hell schraffiert, Flächen mit auffälliger Baumart (`NOTABLE_TR`) ab Stufe 16 mit Baum-Umriss.
  Daten: Original-ZIP als Release `tasveg-data` (wird vom Workflow geladen) oder lokal über `TASVEG_SRC=…zip`.
  Quelle: TASVEG 5.0 from www.theLIST.tas.gov.au ©State of Tasmania (CC BY 3.0 AU).
- **Riesenbäume** aus `render/pois/tasmanien_baeume.csv` (Name;Breite, Länge): goldener Stern ab z9, Name ab z12
  (mit `MAGNIFY=2` sichtbar ab 10 bzw. 13).
- Zusätzlich importierte OSM-Schlüssel: `locked`, `4wd_only`, `smoothness`, `motor_vehicle`.

---

## 6. Erkenntnisse und Stolpersteine

**Mapnik / Stil**
- Eigene Layer: SQL **in einer Zeile**, XML-escaped (`&lt;`), und immer `geometry_field=way` und
  `srid=3857` angeben. Mehrzeiliges SQL führte zu „could not determine geometry“.
- Symbole, die nicht verschwinden dürfen: `allow-overlap="true"` (sonst verdrängt z.B. ein Gipfelname den Aussichtspunkt).
- Schriften: Mapnik findet nur registrierte Dateien. `render_tiles.py` registriert `/usr/share/fonts`,
  `/usr/local/share/fonts` und `/usr/share/wine/fonts` (Tahoma). `render_preview.py --set-font` schreibt
  OTMs `inc/fontset-settings.xml.inc` um. Die „SVG PARSING ERROR“-Meldungen im Log sind harmlos.
- Eigene Layer kommen ganz oben in die Karte (vor `</Map>`), damit sie über allem liegen.

**MBTiles**
- MBTiles zählt die Zeilen von unten (TMS): `tile_row = 2^z − 1 − y`.
- Deduplizierung: Tabelle `images` (md5 → Bild) und `map` (z/x/y → md5), dazu eine View `tiles` mit den
  Standardspalten – jeder MBTiles-Leser kommt damit klar. Meer- und gleichförmige Waldkacheln werden so nur
  einmal gespeichert (bei Tasmanien z0–13: 11 402 Kacheln, 8 529 verschiedene).
- WebP Qualität 85 ist etwa 40 % kleiner als PNG8 und auf dem Handy nicht langsamer.
- Metadaten `tile_size` und `scale` werden gesetzt; LoriMaps liest die Kachelgrösse aber aus dem ersten Bild.

**Höhenmodell**
- Copernicus GLO-30 ist frei (AWS, ohne Anmeldung). Fehlende Kacheln = Meer, das ist normal.
- Ohne Übersichten (`gdaladdo`) lesen niedrige Zoomstufen das volle 30-m-Raster – sehr langsam.
- Die Gipfel-Dominanz („isolation“) mit dem Standardradius 100 km ist bei grossen Gebieten extrem langsam;
  25 km reichen für die Kartendarstellung.

**Grosse Gebiete / Laufzeit**
- Gemessen (GitHub-Rechner mit 4 Kernen):
  - Thurgau z0–16, PNG: 19 464 Kacheln, 892 MB, 9,4 Kacheln/s
  - Huon–Hartz z0–16, WebP: 6 934 Kacheln, 185 MB, ~11 min Rendern
  - Tasmanien z0–13, WebP: 11 402 Kacheln, **532 MB**; auf 8 Rechner verteilt je ~55 min Rendern,
    davon 50 min für z13. Insgesamt ca. 30 Kern-Stunden.
- Die Vorbereitung (Import, Höhenmodell, Vorverarbeitung) dauert für Tasmanien nur ~10–20 min.
- **Engpass ist z13+ in Tasmanien: ~10 s pro Kachel.** Wahrscheinliche Ursache: riesige Flächen
  (Wald, Nationalparks, Schutzgebiete als Multipolygone mit sehr vielen Punkten), die für jede Kachel
  ganz aus der Datenbank geholt werden. Ideen, falls z14–16 für ganz Tasmanien kommen soll:
  - grosse Polygone in der Datenbank vorab mit `ST_Subdivide` zerlegen (nur für Füllflächen, nicht für Grenzlinien
    und Beschriftungen) oder in den Landuse-Layern `ST_ClipByBox2D(way, !bbox!)` verwenden;
  - Zeit pro Layer messen (Mapnik mit `MAPNIK_LOG`/Stoppuhr pro Layer), bevor man optimiert.
  - Abschätzung ohne Optimierung: jede Stufe ×4 → z14 ~120, z15 ~500 Kern-Stunden. Mit TASVEG statt
    OTM-Wald fällt ein Teil der grossen Waldpolygone ohnehin weg.
- Laptop mit 8 schnellen Kernen: Tasmanien z0–13 grob 3–4 Stunden. Kleinere Gebiete bis z16 (wie Huon–Hartz) in Minuten.
- Paralleles Rendern auf mehreren Rechnern: `SHARDS=8` und `SHARD=0…7`, jede Instanz schreibt
  `NAME-otm.partK.mbtiles`, danach `python3 merge_mbtiles.py ziel.mbtiles *.part*.mbtiles`.

**GitHub Actions (bisheriger Weg)**
- Maximal 6 h pro Job, daher die Aufteilung auf 8 parallele Jobs plus Zusammenführen.
- Release-Dateien dürfen höchstens 2 GB gross sein.

---

## 7. Nächstes Projekt: TASVEG statt OTM-Wald

Vorbereitung: `docs/otm-farben.png` zeigt alle OpenTopoMap-Flächenfarben (erzeugt mit `docs/colortable.py`).

Geplanter Weg:
1. Klassifizierte TASVEG-Daten (Shapefile/GeoPackage mit einer Klassenspalte) in die Datenbank `gis`:
   `ogr2ogr -f PostgreSQL PG:dbname=gis tasveg.gpkg -nln tasveg -t_srs EPSG:3857 -lco GEOMETRY_NAME=way -nlt PROMOTE_TO_MULTI`
   und danach `ST_Subdivide` in eine Tabelle `tasveg_sub` (TASVEG hat sehr detaillierte Polygone).
2. In `customize_style.py` einen Layer `own-tasveg` **auf Höhe der Landnutzung, unter der Schummerung**
   einfügen, mit einer Regel/Farbe pro Klasse.
3. Die OTM-Regeln für Wald und Gebüsch (`landuse=forest`, `natural=wood`, `natural=scrub`, …) in den
   Layern `landuse-lowzoom`, `landuse` und `landuse-over-hillshade` innerhalb des TASVEG-Gebiets abschalten.
4. Mit `MODE=preview` und `SKIP_DATA=1` die Farben abstimmen.

---

## Lizenzen

Kartendaten © OpenStreetMap-Mitwirkende (ODbL). Höhenmodell: Copernicus DEM, © DLR e.V. 2010–2014 und
© Airbus Defence and Space GmbH 2014–2018, bereitgestellt im Rahmen von COPERNICUS durch die EU und ESA.
Kartenstil: OpenTopoMap (CC-BY-SA). Die Attribution steht automatisch in den Metadaten jeder MBTiles-Datei.
