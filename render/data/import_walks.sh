#!/usr/bin/env bash
# Own walk data for the "walks" overlay into the database "gis":
#   bigtree_hikes  render/pois/big_tree_hikes.geojson (tracks from bigtreestate.com and others, car routes removed)
#   gsw_tracks     render/data/gsw_tracks.geojson (60 Great Short Walks of Tasmania: nr, name, grade)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
for spec in "$HERE/../pois/big_tree_hikes.geojson:bigtree_hikes" "$HERE/gsw_tracks.geojson:gsw_tracks"; do
  f=${spec%%:*}; t=${spec##*:}
  if [ -f "$f" ]; then
    ogr2ogr -f PostgreSQL PG:dbname=gis "$f" -nln "$t" -overwrite -t_srs EPSG:3857 -lco GEOMETRY_NAME=way -nlt PROMOTE_TO_MULTI
  else
    psql -q -d gis -c "DROP TABLE IF EXISTS $t; CREATE TABLE $t (way geometry(MultiLineString,3857), nr text, name text, grade text);"
  fi
done
psql -d gis -At -c "SELECT 'big tree hikes: ' || count(*) FROM bigtree_hikes;"
psql -d gis -At -c "SELECT 'great short walks: ' || count(*) FROM gsw_tracks;"
