#!/usr/bin/env bash
# LIST_PLUS (on top of variant C): as many roads and tracks as possible from both sources, nothing overwritten.
#  1) OSM roads get the LIST road class and access of the LIST road next to them (list_class, list_user):
#     "Access Road" is drawn thinner with a dashed edge, "Private" gets the label "privat".
#  2) LIST roads that OSM does not have are added as roads (in their LIST class).
#  3) LIST vehicular tracks along an OSM path/footway are not drawn (a footway stays a footway).
#  4) OSM tracks that LIST does not know at all are drawn as track grade 5 (the most uncertain kind).
# Runs after import_list_transport.sh.
set -euo pipefail
psql -q -v ON_ERROR_STOP=1 -d gis <<'SQL'
DROP TABLE IF EXISTS list_road;
CREATE TABLE list_road AS
  SELECT row_number() OVER () AS id, tran_class, user_type, surface_ty, pri_name, (ST_Dump(way)).geom AS way
    FROM list_transport WHERE trans_type = 'Road' AND tran_class NOT IN ('Vehicular Track', 'Not Applicable');
CREATE INDEX ON list_road USING gist (way);
ANALYZE list_road;

-- 1) LIST class and access for OSM roads (the LIST road nearest to the middle of the OSM way)
ALTER TABLE planet_osm_line ADD COLUMN IF NOT EXISTS list_class text, ADD COLUMN IF NOT EXISTS list_user text;
UPDATE planet_osm_line o SET (list_class, list_user) = (
    SELECT l.tran_class, l.user_type FROM list_road l
     WHERE ST_DWithin(l.way, ST_LineInterpolatePoint(o.way, 0.5), 20)
     ORDER BY ST_Distance(l.way, ST_LineInterpolatePoint(o.way, 0.5)) LIMIT 1)
 WHERE o.highway IN ('motorway','trunk','primary','secondary','tertiary','unclassified','residential',
                     'living_street','service','road','motorway_link','trunk_link','primary_link',
                     'secondary_link','tertiary_link','track')
   AND GeometryType(o.way) = 'LINESTRING';

-- 2) LIST roads without any OSM way within 20 m: added (pieces of at least 40 m)
DROP TABLE IF EXISTS list_road_new;
CREATE TABLE list_road_new AS
  SELECT l.id, l.tran_class, l.user_type, l.surface_ty, l.pri_name, (ST_Dump(
           CASE WHEN b.g IS NULL THEN l.way ELSE ST_Difference(l.way, b.g) END)).geom AS way
    FROM list_road l
    LEFT JOIN LATERAL (SELECT ST_Union(ST_Buffer(o.way, 20)) AS g FROM planet_osm_line o
                        WHERE o.highway IS NOT NULL AND ST_DWithin(o.way, l.way, 20)) b ON true;
DELETE FROM list_road_new WHERE GeometryType(way) <> 'LINESTRING' OR ST_Length(way) * 0.73 < 40;
INSERT INTO planet_osm_line (osm_id, highway, name, surface, list_class, list_user, z_order, way)
SELECT -(3000000000000 + row_number() OVER ()),
       CASE tran_class WHEN 'National/State Highway' THEN 'trunk' WHEN 'Arterial Road' THEN 'primary'
                       WHEN 'Sub Arterial Road' THEN 'secondary' WHEN 'Collector Road' THEN 'tertiary'
                       ELSE 'unclassified' END,
       NULLIF(pri_name, ''),
       CASE surface_ty WHEN 'Sealed' THEN 'paved' WHEN 'Unsealed' THEN 'unpaved' WHEN '4WD required' THEN 'unpaved' END,
       tran_class, user_type, 330, way
  FROM list_road_new;

-- 3) LIST vehicular tracks that OSM has as a path or footway: the footway wins
ALTER TABLE list_transport ADD COLUMN IF NOT EXISTS on_osm_path boolean DEFAULT false;
UPDATE list_transport l SET on_osm_path = true
  WHERE l.tran_class = 'Vehicular Track' AND ST_Length(l.way) > 0
    AND (SELECT ST_Length(ST_Intersection(l.way, ST_Buffer(ST_Collect(o.way), 15)))
         FROM planet_osm_line o WHERE o.highway IN ('path','footway','bridleway','steps') AND ST_DWithin(o.way, l.way, 15))
        > 0.6 * ST_Length(l.way);

-- 4) OSM tracks that LIST does not know at all (less than 30 % near any LIST segment): grade 5
UPDATE planet_osm_line o SET tracktype = 'grade5'
  WHERE o.highway = 'track' AND NOT COALESCE(o.list_dup, false) AND ST_Length(o.way) > 0
    AND COALESCE((SELECT ST_Length(ST_Intersection(o.way, ST_Buffer(ST_Collect(l.way), 25)))
                  FROM list_transport l WHERE ST_DWithin(l.way, o.way, 25)), 0) < 0.3 * ST_Length(o.way);
ANALYZE planet_osm_line; ANALYZE list_transport;
SQL
psql -d gis -At -c "SELECT 'OSM roads with LIST class: ' || string_agg(list_class || '/' || list_user || '=' || n, ', ') FROM (SELECT list_class, list_user, count(*) n FROM planet_osm_line WHERE list_class IS NOT NULL AND osm_id > 0 GROUP BY 1, 2 ORDER BY 3 DESC) t;"
psql -d gis -At -c "SELECT 'LIST roads added (not in OSM): ' || count(*) || ', ' || round(sum(ST_Length(way)) * 0.73 / 1000) || ' km' FROM planet_osm_line WHERE osm_id < -3000000000000;"
psql -d gis -At -c "SELECT 'LIST vehicular tracks kept as OSM footway: ' || count(*) FROM list_transport WHERE on_osm_path;"
psql -d gis -At -c "SELECT 'OSM tracks not in LIST (drawn as grade 5): ' || count(*) FROM planet_osm_line WHERE highway = 'track' AND tracktype = 'grade5';"
