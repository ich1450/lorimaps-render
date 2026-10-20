#!/usr/bin/env python3
"""Render a Mapnik style into a raster MBTiles file.

Tiles are rendered at 256*scale pixels with Mapnik's scale_factor, i.e. scale=2 gives
"@2x" 512 px tiles that show the same area and the same map rules as normal 256 px tiles,
only with twice the resolution.

--magnify 2 draws everything twice as large on the same tiles (scale_factor = scale*magnify):
each zoom level then shows the content of the next lower level, sharp and enlarged.
"""
import argparse
import hashlib
import io
import math
import multiprocessing as mp
import os
import sqlite3
import sys
import time

import mapnik

R = 20037508.342789244  # half of the Web Mercator world width in metres

_map = None
_args = None


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(max(min(lat, 85.0511), -85.0511))
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_bounds(x, y, z):
    size = 2 * R / (2 ** z)
    minx = -R + x * size
    maxy = R - y * size
    return minx, maxy - size, minx + size, maxy


def register_fonts():
    for root in ("/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/wine/fonts"):
        for dirpath, _, files in os.walk(root, followlinks=True):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc")):
                    mapnik.FontEngine.register_font(os.path.join(dirpath, f))


def init_worker(args):
    global _map, _args
    _args = args
    register_fonts()
    px = 256 * args.scale
    _map = mapnik.Map(px, px)
    mapnik.load_map(_map, args.style)
    # larger symbols and labels need a wider margin, otherwise they are cut at tile edges
    _map.buffer_size = max(_map.buffer_size, 128) * args.magnify


def render(tile):
    z, x, y = tile
    minx, miny, maxx, maxy = tile_bounds(x, y, z)
    _map.zoom_to_box(mapnik.Box2d(minx, miny, maxx, maxy))
    im = mapnik.Image(_map.width, _map.height)
    try:
        mapnik.render(_map, im, float(_args.scale * _args.magnify))
    except Exception as e:  # keep going, report at the end
        return z, x, y, None, str(e)
    if _args.format.startswith("webp"):
        # WebP via Pillow (lossy, quality after the colon, e.g. "webp:85")
        from PIL import Image
        quality = int(_args.format.split(":")[1]) if ":" in _args.format else 85
        png = Image.open(io.BytesIO(im.tostring("png32")))
        buf = io.BytesIO()
        png.convert("RGB").save(buf, "WEBP", quality=quality, method=5)
        return z, x, y, buf.getvalue(), None
    return z, x, y, im.tostring(_args.format), None


def tiles_for(bbox, zmin, zmax):
    w, s, e, n = bbox
    for z in range(zmin, zmax + 1):
        x0, y0 = lonlat_to_tile(w, n, z)
        x1, y1 = lonlat_to_tile(e, s, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--style", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--bbox", required=True, help="west,south,east,north")
    p.add_argument("--minzoom", type=int, default=8)
    p.add_argument("--maxzoom", type=int, default=16)
    p.add_argument("--scale", type=int, default=2)
    p.add_argument("--magnify", type=float, default=1.0, help="draw lines, symbols and labels this much larger")
    p.add_argument("--format", default="png8:m=h")
    p.add_argument("--name", default="map")
    p.add_argument("--processes", type=int, default=os.cpu_count())
    p.add_argument("--shard", type=int, default=0, help="render only this part (0-based) ...")
    p.add_argument("--shards", type=int, default=1, help="... of this many parts (for parallel jobs)")
    args = p.parse_args()

    register_fonts()
    faces = set(mapnik.FontEngine.face_names())
    print(f"{len(faces)} font faces registered", flush=True)

    bbox = [float(v) for v in args.bbox.split(",")]
    tiles = list(tiles_for(bbox, args.minzoom, args.maxzoom))
    if args.shards > 1:
        # blocks of 8x8 tiles stay together (shared database pages and caches)
        tiles = [t for t in tiles if ((t[1] >> 3) * 7919 + (t[2] >> 3) * 104729 + t[0]) % args.shards == args.shard]
        print(f"shard {args.shard + 1}/{args.shards}", flush=True)
    print(f"{len(tiles)} tiles, zoom {args.minzoom}-{args.maxzoom}, {256 * args.scale} px, magnify {args.magnify}, {args.processes} processes", flush=True)

    if os.path.exists(args.out):
        os.remove(args.out)
    db = sqlite3.connect(args.out)
    # identical tiles (sea, lakes, uniform forest) are stored only once: "map" points to "images",
    # "tiles" is a view with the standard MBTiles columns, so readers need nothing special
    db.executescript("""
        PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE metadata (name TEXT, value TEXT);
        CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
        CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
        CREATE TABLE images (tile_id TEXT, tile_data BLOB);
        CREATE UNIQUE INDEX images_id ON images (tile_id);
        CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column,
            map.tile_row AS tile_row, images.tile_data AS tile_data FROM map JOIN images ON images.tile_id = map.tile_id;
    """)
    w, s, e, n = bbox
    meta = {
        "name": args.name,
        "format": "webp" if args.format.startswith("webp") else "png",
        "type": "baselayer",
        "version": "1",
        "description": f"OpenTopoMap style, {256 * args.scale} px tiles, magnify {args.magnify}",
        "attribution": "Kartendaten: © OpenStreetMap-Mitwirkende, Copernicus DEM (© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA) | Kartendarstellung: © OpenTopoMap (CC-BY-SA)",
        "bounds": f"{w},{s},{e},{n}",
        "center": f"{(w + e) / 2},{(s + n) / 2},{min(args.maxzoom, 12)}",
        "minzoom": str(args.minzoom),
        "maxzoom": str(args.maxzoom),
        "scale": str(args.scale),
        "tile_size": str(256 * args.scale),
        "magnify": str(args.magnify),
    }
    db.executemany("INSERT INTO metadata VALUES (?, ?)", meta.items())

    start = time.time()
    done = errors = 0
    zoom_time = {}
    last = time.time()
    first_error = None
    with mp.Pool(args.processes, initializer=init_worker, initargs=(args,)) as pool:
        for z, x, y, data, err in pool.imap_unordered(render, tiles, chunksize=8):
            done += 1
            now = time.time()
            zoom_time[z] = zoom_time.get(z, 0) + (now - last)
            last = now
            if err:
                errors += 1
                first_error = first_error or f"{z}/{x}/{y}: {err}"
            else:
                tid = hashlib.md5(data).hexdigest()
                db.execute("INSERT OR IGNORE INTO images VALUES (?, ?)", (tid, sqlite3.Binary(data)))
                db.execute("INSERT INTO map VALUES (?, ?, ?, ?)", (z, x, (2 ** z - 1) - y, tid))
            if done % 500 == 0 or done == len(tiles):
                db.commit()
                el = time.time() - start
                print(f"  {done}/{len(tiles)} tiles, {el / 60:.1f} min, {done / el:.1f} tiles/s, {errors} errors", flush=True)
    db.commit()
    unique = db.execute("SELECT count(*) FROM images").fetchone()[0]
    print("time per zoom level (wall clock, all processes):", ", ".join(f"z{z}: {t / 60:.1f} min" for z, t in sorted(zoom_time.items())))
    print(f"{done - errors} tiles, {unique} unique images ({done - errors - unique} duplicates stored once)")
    db.execute("VACUUM")
    db.close()
    print(f"written {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)")
    if errors:
        print(f"{errors} tiles failed, first error: {first_error}")
        if errors == len(tiles):
            sys.exit(1)


if __name__ == "__main__":
    main()
