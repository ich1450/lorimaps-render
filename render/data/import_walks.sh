#!/usr/bin/env bash
# Own walk data for the "walks" overlay into the database "gis":
#   bigtree_hikes  render/pois/big_tree_hikes.geojson (tracks from bigtreestate.com and others, car routes removed)
#   gsw_tracks     60 Great Short Walks of Tasmania (number, name, level, time, distance from gsw_walks.csv).
#                  The booklet has no coordinates: the track lines are found by name (gsw_spec.csv: regular
#                  expression, approximate position and search radius) in the LIST transport segments
#                  (walking tracks and vehicular tracks), and in OpenStreetMap paths where LIST has nothing.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ogr2ogr -f PostgreSQL PG:dbname=gis "$HERE/../pois/big_tree_hikes.geojson" -nln bigtree_hikes -overwrite \
  -t_srs EPSG:3857 -lco GEOMETRY_NAME=way -nlt PROMOTE_TO_MULTI

HAS_LIST=$(psql -d gis -At -c "SELECT to_regclass('list_transport') IS NOT NULL")
if [ "$HAS_LIST" = t ]; then
  LIST_PART="SELECT s.nr, (ST_Dump(l.way)).geom AS way, 'LIST' AS src FROM gsw_spec s JOIN list_transport l
      ON (l.trans_type = 'Track' OR l.tran_class IN ('Vehicular Track', 'Walking'))
     AND l.pri_name ~* s.pattern AND ST_DWithin(l.way, s.centre, s.radius)"
else
  LIST_PART="SELECT NULL::text AS nr, NULL::geometry AS way, NULL::text AS src WHERE false"
fi

psql -q -v ON_ERROR_STOP=1 -d gis <<SQL
DROP TABLE IF EXISTS gsw_walks, gsw_spec, gsw_tracks;
CREATE TABLE gsw_walks (nr text, name text, level text, time text, distance text, search text);
\copy gsw_walks FROM '$HERE/gsw_walks.csv' WITH (FORMAT csv, DELIMITER ';', HEADER true)
CREATE TABLE gsw_spec (nr text, pattern text, lon float, lat float, radius_km float);
\copy gsw_spec FROM '$HERE/gsw_spec.csv' WITH (FORMAT csv, DELIMITER ';', HEADER true)
ALTER TABLE gsw_spec ADD COLUMN centre geometry, ADD COLUMN radius float;
-- Web Mercator metres are 1/cos(latitude) times longer than real metres
UPDATE gsw_spec SET centre = ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 3857),
                    radius = radius_km * 1000 / cos(radians(lat));
CREATE TEMP TABLE gsw_list AS $LIST_PART;
CREATE TEMP TABLE gsw_osm AS
  SELECT s.nr, (ST_Dump(o.way)).geom AS way, 'OSM' AS src FROM gsw_spec s JOIN planet_osm_line o
      ON o.highway IN ('path', 'footway', 'track', 'steps', 'bridleway', 'cycleway')
     AND o.name ~* s.pattern
     AND ST_DWithin(o.way, s.centre, s.radius)
   WHERE s.nr NOT IN (SELECT nr FROM gsw_list);
CREATE TABLE gsw_tracks AS
  SELECT w.nr, w.name, w.level, w.time, w.distance, t.src, ST_Multi(ST_LineMerge(ST_Collect(t.way))) AS way
    FROM (SELECT * FROM gsw_list UNION ALL SELECT * FROM gsw_osm) t JOIN gsw_walks w ON w.nr = t.nr
   GROUP BY 1, 2, 3, 4, 5, 6;
CREATE INDEX gsw_tracks_way ON gsw_tracks USING gist (way);
SQL
psql -d gis -At -c "SELECT 'big tree hikes: ' || count(*) FROM bigtree_hikes;"
psql -d gis -At -c "SELECT 'great short walks found: ' || count(*) || ' (' || string_agg(nr || ' ' || src || ' ' || round(ST_Length(way) * cos(radians(ST_Y(ST_Transform(ST_Centroid(way), 4326)))))::int || ' m', ', ' ORDER BY nr::int) || ')' FROM gsw_tracks;"
psql -d gis -At -c "SELECT 'great short walks not found in this area: ' || string_agg(nr || ' ' || name, ', ' ORDER BY nr::int) FROM gsw_walks WHERE nr NOT IN (SELECT nr FROM gsw_tracks);"
