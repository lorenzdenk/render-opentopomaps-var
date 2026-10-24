#!/usr/bin/env bash
# Forest types into the database "gis" (FOREST_TYPES=1):
#   forest_type(cls, way)  OSM forest (landuse=forest/wood, natural=wood) cut into pieces by forest type class
#                          (forest/build_forest.py); forest without information gets class 7 "other"
# usage: import_forest.sh <workdir>
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$1"
RASTER=$(bash "$HERE/data/prepared.sh" forest "$WORK/prep")
mkdir -p "$WORK/forest"; cd "$WORK/forest"
rm -f classes.gpkg
gdal_polygonize.py -q -8 "$RASTER" -f GPKG classes.gpkg classes cls
ogr2ogr -f PostgreSQL PG:dbname=gis classes.gpkg classes -nln forest_class_raw -overwrite -lco GEOMETRY_NAME=way \
  -a_srs EPSG:3857 -nlt PROMOTE_TO_MULTI --config PG_USE_COPY YES -gt 100000
psql -q -v ON_ERROR_STOP=1 -d gis <<'SQL'
DROP TABLE IF EXISTS forest_class, forest_osm, forest_type;
-- smooth the pixel steps a little, small pieces for fast intersections
CREATE TABLE forest_class AS
  SELECT cls, ST_Subdivide(ST_MakeValid(ST_SimplifyPreserveTopology(way, 3)), 256) AS way FROM forest_class_raw;
CREATE INDEX ON forest_class USING gist (way);
CREATE TABLE forest_osm AS
  SELECT osm_id, ST_MakeValid(way) AS way FROM planet_osm_polygon
  WHERE landuse IN ('forest', 'wood') OR "natural" = 'wood';
CREATE INDEX ON forest_osm USING gist (way);
CREATE TABLE forest_type AS
  SELECT CASE WHEN c.cls BETWEEN 1 AND 8 THEN c.cls ELSE 7 END AS cls,
         (ST_Dump(ST_CollectionExtract(ST_Intersection(f.way, c.way), 3))).geom AS way
  FROM forest_osm f JOIN forest_class c ON ST_Intersects(f.way, c.way);
DELETE FROM forest_type WHERE ST_Area(way) < 20;
CREATE INDEX ON forest_type USING gist (way);
ANALYZE forest_type;
SQL
psql -d gis -At -c "SELECT 'forest types (ha): ' || string_agg(cls || '=' || ha, ', ') FROM (SELECT cls, round(sum(ST_Area(way)) / 10000 * 0.45) AS ha FROM forest_type GROUP BY cls ORDER BY cls) t;"
