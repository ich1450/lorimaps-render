#!/usr/bin/env python3
"""Downloads LIST OpenDataWFS layers for all of Tasmania (CC BY 3.0 AU), in parallel grid cells
(the service returns at most 2000 features per request), and writes one GeoJSONSeq file per layer
(one feature per line, written as it comes: millions of contour lines do not fit in memory).
Usage: prepare_list_data.py <out dir> <layer>:<name>:<fields> ...
       e.g. 16:contours:ELEVATION 23:hydro_lines:HYDLNTY1,HYDLNTY2,HYD_CLASS,NAME"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = sys.argv[1]
UA = {"User-Agent": "LoriMaps-render (+https://github.com/lorenzdenk/lorimaps-render)"}
W, S, E, N = 143.5, -43.9, 148.6, -39.3     # Tasmania with King and Flinders Island
STEP = 0.25


def fetch_cell(args):
    layer, fields, w, s, e, n = args
    url = f"https://services.thelist.tas.gov.au/arcgis/rest/services/Public/OpenDataWFS/MapServer/{layer}/query"
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "OBJECTID," + fields, "outSR": 4326,
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 2000, "f": "geojson"})
        for attempt in range(8):
            try:
                with urllib.request.urlopen(urllib.request.Request(url + "?" + q, headers=UA), timeout=300) as r:
                    page = json.load(r)
                break
            except Exception as ex:
                print(f"retry layer {layer} cell {w},{s} offset {offset}: {ex}", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            raise SystemExit(f"ERROR: layer {layer} cell {w},{s} failed")
        part = page.get("features", [])
        feats += part
        if len(part) < 2000 and not page.get("exceededTransferLimit"):
            return feats
        offset += len(part)


for spec in sys.argv[2:]:
    layer, name, fields = spec.split(":")
    cells = []
    x = W
    while x < E:
        y = S
        while y < N:
            cells.append((layer, fields, round(x, 4), round(y, 4), round(min(x + STEP, E), 4), round(min(y + STEP, N), 4)))
            y += STEP
        x += STEP
    t0 = time.time()
    seen, n = set(), 0
    with open(f"{OUT}/{name}.geojsonl", "w") as out, ThreadPoolExecutor(8) as pool:
        for i, feats in enumerate(pool.map(fetch_cell, cells)):
            for f in feats:       # features crossing cell borders come several times
                oid = f.get("properties", {}).get("OBJECTID", f.get("id"))
                if oid in seen:
                    continue
                seen.add(oid)
                out.write(json.dumps(f) + "\n")
                n += 1
            if i % 40 == 0:
                print(f"layer {layer} ({name}): {i + 1}/{len(cells)} cells, {n} features, "
                      f"{(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"layer {layer} ({name}): {n} features in {(time.time() - t0) / 60:.1f} min", flush=True)
