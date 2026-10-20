#!/usr/bin/env bash
# TASVEG 5.0 (www.theLIST.tas.gov.au, ©State of Tasmania, CC BY 3.0 AU) into the database "gis":
#   tasveg          vegetation polygons with class A ("Waldgefühl", 1-6), forest structure, cut into small pieces
#   tasveg_low      simplified larger polygons for zoom levels up to 11
#   tasveg_notable  one point per polygon with a notable tree species
# Source: the original ZIP from theLIST, as GitHub release "tasveg-data" of this repository,
# or a local file/folder in TASVEG_SRC (ZIP, .shp or folder containing TASVEG_5_0.shp).
# Usage: import_tasveg.sh <workdir> <west> <south> <east> <north>
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$1"; W="$2"; S="$3"; E="$4"; N="$5"
mkdir -p "$WORK/tasveg"
cd "$WORK/tasveg"

SHP=$(find . -name 'TASVEG_*.shp' 2>/dev/null | head -1 || true)
if [ -z "$SHP" ]; then
  if [ -n "${TASVEG_SRC:-}" ]; then
    case "$TASVEG_SRC" in
      *.zip) unzip -q -o "$TASVEG_SRC" ;;
      *.shp) cp "${TASVEG_SRC%.shp}".* . ;;
      *) cp -r "$TASVEG_SRC"/. . ;;
    esac
  else
    echo "downloading TASVEG from release tasveg-data of $GITHUB_REPOSITORY"
    GH_TOKEN="${GITHUB_TOKEN:-}" gh release download tasveg-data -R "$GITHUB_REPOSITORY" -p '*' -D . --clobber
    for z in *.zip; do [ -f "$z" ] && unzip -q -o "$z" && rm "$z"; done
  fi
  SHP=$(find . -name 'TASVEG_*.shp' | head -1)
fi
[ -n "$SHP" ] || { echo "ERROR: no TASVEG shapefile found"; exit 1; }
echo "TASVEG source: $SHP"

# only the needed columns, clipped to the region, in Web Mercator
ogr2ogr -f PostgreSQL PG:dbname=gis "$SHP" -nln tasveg_raw -overwrite \
  -select VEGCODE,FOREST_STR,NOTABLE_TR -spat "$W" "$S" "$E" "$N" -spat_srs EPSG:4326 \
  -t_srs EPSG:3857 -lco GEOMETRY_NAME=way -nlt PROMOTE_TO_MULTI -makevalid --config PG_USE_COPY YES -gt 100000

# class table (code;...;Einteilung_A;Einteilung_B) -> SQL
python3 - "$HERE/klassen_waldtypen.csv" > classes.sql <<'EOF'
import csv, sys
rows = list(csv.reader(open(sys.argv[1], encoding="utf-8-sig"), delimiter=";"))
print("DROP TABLE IF EXISTS tasveg_class; CREATE TABLE tasveg_class (code text PRIMARY KEY, cls_a int, cls_b int);")
for r in rows[1:]:
    print(f"INSERT INTO tasveg_class VALUES ('{r[0]}', {int(r[4][0])}, {int(r[5][0])});")
EOF
psql -q -d gis -f classes.sql

psql -q -d gis <<'SQL'
DROP TABLE IF EXISTS tasveg, tasveg_low, tasveg_notable;
CREATE TABLE tasveg AS
  SELECT c.cls_a, c.cls_b, r.vegcode, COALESCE(r.forest_str, '') AS forest_str, ST_Subdivide(r.way, 256) AS way
  FROM tasveg_raw r JOIN tasveg_class c ON c.code = r.vegcode WHERE c.cls_a > 0;
CREATE INDEX tasveg_way ON tasveg USING gist (way);
CREATE TABLE tasveg_low AS
  SELECT cls_a, ST_Subdivide(ST_SimplifyPreserveTopology(way, 60), 256) AS way FROM (
    SELECT c.cls_a, r.way FROM tasveg_raw r JOIN tasveg_class c ON c.code = r.vegcode
    WHERE c.cls_a > 0 AND ST_Area(r.way) > 40000) t;
CREATE INDEX tasveg_low_way ON tasveg_low USING gist (way);
CREATE TABLE tasveg_notable AS
  SELECT notable_tr, ST_PointOnSurface(way) AS way, ST_Area(way) AS area FROM tasveg_raw
  WHERE COALESCE(notable_tr, '') <> '';
CREATE INDEX tasveg_notable_way ON tasveg_notable USING gist (way);
ANALYZE tasveg; ANALYZE tasveg_low; ANALYZE tasveg_notable;
SQL
psql -d gis -At -c "SELECT 'TASVEG pieces by class A: ' || string_agg(cls_a || '=' || n, ', ') FROM (SELECT cls_a, count(*) n FROM tasveg GROUP BY 1 ORDER BY 1) t;"
psql -d gis -At -c "SELECT 'woodland pieces: ' || count(*) FILTER (WHERE forest_str = 'Woodland') || ', notable tree points: ' || (SELECT count(*) FROM tasveg_notable) FROM tasveg;"
