#!/usr/bin/env python3
"""Own changes to the OpenTopoMap style, applied to a fresh checkout before import and rendering.

Each patch checks that the original text is still there, so a change upstream fails loudly
instead of being silently skipped.

  1. extra OSM keys imported: locked, 4wd_only, smoothness, motor_vehicle
  2. viewpoints without a "direction" tag are drawn (all-round symbol), and never hidden by labels
  3. OpenTopoMap's black tracks with clearer track types: grade2 thicker than grade3,
     grade4 densely dashed, grade5 dashed with wide gaps
  4. paths/tracks not visible on the ground or without public access: light grey;
     "4WD" next to tracks with 4wd_only=yes or very bad smoothness; trail names from zoom 14
  5. camp sites: green symbol from zoom 11, name from zoom 13
  6. locked gates and barriers: red "no entry" disc from zoom 13
"""
import shutil
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
mapnik_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
# EARLY_TRAILS=2: paths, tracks and trail names two zoom levels earlier (sparse areas like Tasmania)
EARLY = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else 0
# TASVEG=1: vegetation of Tasmania from TASVEG instead of OpenStreetMap's forest and scrub
TASVEG = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else 0
xml_path = mapnik_dir / "opentopomap.xml"
xml = xml_path.read_text()


def patch(old, new, what, text=None):
    global xml
    src = xml if text is None else text
    if old not in src:
        sys.exit(f"style patch failed ({what}): original text not found")
    out = src.replace(old, new, 1)
    print(f"patched: {what}")
    if text is None:
        xml = out
    return out


def one_line(sql):
    return " ".join(sql.split())


# ---------------------------------------------------------------- 1) import more keys
style_file = mapnik_dir / "osm2pgsql" / "opentopomap.style"
s = style_file.read_text()
for line in ["node,way   locked       text         linear",
             "way        4wd_only     text         linear",
             "way        smoothness   text         linear",
             "node,way   motor_vehicle text        linear"]:
    key = line.split()[1]
    if not any(l.split()[1:2] == [key] for l in s.splitlines() if l.strip() and not l.startswith("#")):
        s += line + "\n"
style_file.write_text(s)
print("patched: osm2pgsql style (locked, 4wd_only, smoothness, motor_vehicle)")

# own symbols
for svg in (here / "symbols").glob("*.svg"):
    shutil.copy(svg, mapnik_dir / "symbols-otm" / svg.name)

# ---------------------------------------------------------------- 2) viewpoints
patch("viewpointdirection(direction) AS int_dir FROM planet_osm_point WHERE (tourism='viewpoint' AND direction IS NOT NULL)",
      "viewpointdirection(COALESCE(NULLIF(direction,''),'0-360')) AS int_dir FROM planet_osm_point WHERE tourism='viewpoint'",
      "viewpoints without direction")
vp = mapnik_dir / "styles-otm" / "symbols-viewpoint.xml"
vp_text = vp.read_text()
if 'ignore-placement="true"' not in vp_text:
    sys.exit("style patch failed (viewpoint overlap): original text not found")
vp.write_text(vp_text.replace('ignore-placement="true"', 'ignore-placement="true" allow-overlap="true"'))
print("patched: viewpoint symbols always drawn")

# ---------------------------------------------------------------- 3) track widths and dashes
# OpenTopoMap's black tracks, with a clearer difference between the track types:
# grade1 unchanged, grade2 thicker than grade3, grade4 densely dashed, grade5 dashed with wide gaps.
import re
rc_path = mapnik_dir / "styles-otm" / "roads-casing.xml"
rc = rc_path.read_text()


def rc_sub(pattern, repl, what, count=1):
    global rc
    rc, n = re.subn(pattern, repl, rc)
    if n != count:
        sys.exit(f"style patch failed ({what}): {n} matches instead of {count}")
    print(f"patched: {what}")


def rule(zmax, zmin, flt, width, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f"<Rule>&maxscale_zoom{zmax};&minscale_zoom{zmin};<Filter>{flt}</Filter>"
            f'<LineSymbolizer stroke="black" stroke-width="{width}"{d} /></Rule>')


T = "[highway] = 'track' and [tracktype] = "
# unknown tracktype keeps OpenTopoMap's former grade2 line, grade2 gets its own (thicker) rule
rc_sub(r"\(\[tracktype\] = 'grade1' or \[tracktype\] = 'grade3' or \[tracktype\] = 'grade4' or \[tracktype\] = 'grade5' \)\)",
       "([tracktype] = 'grade1' or [tracktype] = 'grade2' or [tracktype] = 'grade3' or [tracktype] = 'grade4' or [tracktype] = 'grade5' ))",
       "zoom 14: unknown tracktype without grade2")
rc_sub(r"\(\[tracktype\] = 'grade1' or \[tracktype\] = 'grade3' or \[tracktype\] = 'grade4' or \[tracktype\] = 'grade5'\) \)",
       "([tracktype] = 'grade1' or [tracktype] = 'grade2' or [tracktype] = 'grade3' or [tracktype] = 'grade4' or [tracktype] = 'grade5') )",
       "zoom 15+: unknown tracktype without grade2")
for zmax, zmin, old_w, w2, w3, d4, w5, d5, old_d5 in (
        (14, 14, "0.5", "1.4", "0.5", "1.8,1.8", "0.6", "3,6", "3,3"),
        (15, 17, "1", "2.0", "0.9", "2.4,2.4", "0.9", "4,8", "4,4")):
    rc_sub(rf"<Rule>\s*&maxscale_zoom{zmax};\s*&minscale_zoom{zmin};\s*<Filter>\[highway\] = 'track' and \(\[tracktype\] = 'grade3' or \[tracktype\] = 'grade4'\)</Filter>\s*"
           rf'<LineSymbolizer stroke="black" stroke-width="{old_w}" />\s*</Rule>',
           rule(zmax, zmin, T + "'grade2'", w2) + rule(zmax, zmin, T + "'grade3'", w3) + rule(zmax, zmin, T + "'grade4'", w3, d4),
           f"zoom {zmax}: grade2/3/4")
    rc_sub(rf"(<Filter>\[highway\] = 'track' and \[tracktype\] = 'grade5'</Filter>\s*)"
           rf'<LineSymbolizer stroke="black" stroke-width="[0-9.]+" stroke-dasharray="{old_d5}" />',
           rf'\g<1><LineSymbolizer stroke="black" stroke-width="{w5}" stroke-dasharray="{d5}" />',
           f"zoom {zmax}: grade5")

# paths on zoom 14 (and the earlier levels copied from it) dotted like on zoom 15+, not dashed
DOTS = {"1.6,1.6": "1.1,2", "1.6,1.6,1.6,1.6,1.6,4.5": "1.1,2,1.1,2,1.1,6", "1.6,1.6,1.6,5": "1.1,2,1.1,8"}
dotted = 0


def path_dots(m):
    global dotted
    block = m.group(0)
    if re.search(r"&maxscale_zoom14;\s*&minscale_zoom14;", block) and ("'path'" in block or "'footway'" in block):
        def sub(d):
            global dotted
            if d.group(1) in DOTS:
                dotted += 1
                return f'stroke-dasharray="{DOTS[d.group(1)]}"'
            return d.group(0)
        block = re.sub(r'stroke-dasharray="([0-9.,]+)"', sub, block)
    return block


rc = re.sub(r"<Rule>.*?</Rule>", path_dots, rc, flags=re.S)
if dotted < 5:
    sys.exit(f"style patch failed (dotted paths): only {dotted} dash patterns found")
print(f"patched: paths on zoom 14 dotted ({dotted} rules)")

# paths and tracks two zoom levels earlier (option), slightly thinner on the extra levels
if EARLY:
    def scaled(block, factor, zmax, zmin):
        block = re.sub(r"&maxscale_zoom\d+;", f"&maxscale_zoom{zmax};", block, count=1)
        block = re.sub(r"&minscale_zoom\d+;", f"&minscale_zoom{zmin};", block, count=1)
        return re.sub(r'stroke-width="([0-9.]+)"', lambda m: f'stroke-width="{float(m.group(1)) * factor:.2f}"', block)

    PATHS = ("'path'", "'footway'", "'bridleway'", "'steps'")
    added = 0

    def early(m):
        global added
        block = m.group(0)
        flt = re.search(r"<Filter>(.*?)</Filter>", block, re.S)
        if not flt:
            return block
        f = flt.group(1)
        if re.search(r"&maxscale_zoom14;\s*&minscale_zoom14;", block):
            is_track = "'track'" in f
            grade12 = is_track and "(not" not in f and ("'grade1'" in f or "'grade2'" in f)
            if (is_track and not grade12) or (not is_track and any(p in f for p in PATHS)):
                added += 1
                return block + scaled(block, 0.7, 12, 13)
        if re.search(r"&maxscale_zoom13;\s*&minscale_zoom13;", block) and "'track'" in f \
                and ("'grade1'" in f or "'grade2'" in f):
            added += 1
            return block + scaled(block, 0.8, 11, 12)
        return block

    rc = re.sub(r"<Rule>.*?</Rule>", early, rc, flags=re.S)
    if added < 5:
        sys.exit(f"style patch failed (early trails): only {added} rules found")
    print(f"patched: paths and tracks two zoom levels earlier ({added} rules)")
rc_path.write_text(rc)

# ---------------------------------------------------------------- 4) faded ways, 4WD labels
NOACCESS = ("(foot IN ('no','private') OR (access IN ('no','private') "
            "AND COALESCE(foot,'') NOT IN ('yes','designated','permissive')))")
INVISIBLE = "trail_visibility IN ('no','horrible')"
PATHLIKE = "highway IN ('path','footway','bridleway','steps','cycleway')"

# faded ways are taken out of OpenTopoMap's road layer and drawn light grey in an own layer
start = xml.index('<Layer name="roads">')
end = xml.index("</Layer>", start) + len("</Layer>")
roads = xml[start:end]
excl = f"NOT COALESCE((highway = 'track' OR {PATHLIKE}) AND ({INVISIBLE} OR {NOACCESS}), false) AND ("
roads = patch("FROM planet_osm_line WHERE ", "FROM planet_osm_line WHERE " + excl, "roads layer: exclude faded ways", roads)
roads = patch(" ORDER BY (CASE WHEN highway IN ('motorway'", ") ORDER BY (CASE WHEN highway IN ('motorway'", "roads layer: close condition", roads)
xml = xml[:start] + roads + xml[end:]

GREY = "#b4b4b4"
FADED_FROM = 12 if EARLY else 14
FADED_STYLE = f"""<Style name="own-faded-ways">
<Rule>&maxscale_zoom{FADED_FROM};<Filter>[highway] = 'track'</Filter>
<LineSymbolizer stroke="{GREY}" stroke-width="1.2"/></Rule>
<Rule>&maxscale_zoom{FADED_FROM};<Filter>[highway] != 'track' and [highway] != 'steps'</Filter>
<LineSymbolizer stroke="{GREY}" stroke-width="0.9" stroke-dasharray="1.1,2"/></Rule>
<Rule>&maxscale_zoom15;<Filter>[highway] = 'steps'</Filter>
<LineSymbolizer stroke="{GREY}" stroke-width="2.5" stroke-dasharray="1,1.5"/></Rule>
</Style>
<Style name="own-4wd">
<Rule>&maxscale_zoom14;
<TextSymbolizer fontset-name="sans-condensed-bold" size="8" fill="#5a3a00" halo-radius="1.2" halo-fill="rgba(255,255,255,0.85)"
 placement="line" spacing="260" max-char-angle-delta="20" dy="-6">'4WD'</TextSymbolizer></Rule>
</Style>"""

FADED_SQL = one_line(f"""(SELECT way, highway FROM planet_osm_line
  WHERE (highway = 'track' OR {PATHLIKE}) AND ({INVISIBLE} OR {NOACCESS})) AS fadedways""")
FOURWD_SQL = one_line("""(SELECT way FROM planet_osm_line WHERE highway = 'track'
  AND ("4wd_only" = 'yes' OR smoothness IN ('very_bad','horrible','very_horrible','impassable'))) AS fourwd""")


def xml_escape(sql):
    return sql.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def layer(name, styles, sql):
    style_refs = "".join(f"<StyleName>{st}</StyleName>" for st in styles)
    return (f'<Layer name="{name}">{style_refs}<Datasource>'
            f'<Parameter name="table">{xml_escape(sql)}</Parameter>'
            '<Parameter name="geometry_field">way</Parameter><Parameter name="srid">3857</Parameter>'
            '<Parameter name="dbname">gis</Parameter>&postgis-settings;</Datasource></Layer>')


insert = "\n".join([FADED_STYLE, layer("own-faded-ways", ["own-faded-ways"], FADED_SQL)])
end = xml.index("</Layer>", xml.index('<Layer name="roads">')) + len("</Layer>")
xml = xml[:end] + "\n" + insert + "\n" + xml[end:]
print("patched: faded-way layer")

# ---------------------------------------------------------------- public parking from zoom 14 (instead of 16)
sr_path = mapnik_dir / "styles-otm" / "symbols-road.xml"
sr, n = re.subn(r"&maxscale_zoom16;(\s*&minscale_zoom17;\s*<Filter>\(\[amenity\] = 'parking'\) and \(\[fee\])",
                r"&maxscale_zoom14;\1", sr_path.read_text())
if n != 2:
    sys.exit(f"style patch failed (parking zoom): {n} matches instead of 2")
sr_path.write_text(sr)
print("patched: public parking from zoom 14")

# ---------------------------------------------------------------- nature reserve borders: thin grey edges along the
# green band for contrast (on both sides, so it works whatever the direction of the outline)
ar_path = mapnik_dir / "styles-otm" / "areas.xml"
ar, n = re.subn(r'(<LineSymbolizer stroke="#85c243" stroke-width="5" stroke-opacity="0.5"/>)',
                r'<LineSymbolizer stroke="#6b6b6b" stroke-width="0.9" stroke-opacity="0.8" offset="2.9"/>'
                r'<LineSymbolizer stroke="#6b6b6b" stroke-width="0.9" stroke-opacity="0.8" offset="-2.9"/>\1', ar_path.read_text())
if n != 3:
    sys.exit(f"style patch failed (reserve borders): {n} matches instead of 3")
ar_path.write_text(ar)
print("patched: grey edges on nature reserve borders")

# ---------------------------------------------------------------- contour numbers without the light halo
ct_path = mapnik_dir / "styles-otm" / "contours.xml"
ct, n = re.subn(r'halo-radius="[0-9.]+"', 'halo-radius="0"', ct_path.read_text())
if n < 2:
    sys.exit(f"style patch failed (contour label halo): {n} matches")
ct_path.write_text(ct)
print(f"patched: contour numbers without halo ({n} rules)")

# ---------------------------------------------------------------- notable single trees (OSM natural=tree with name,
# landmark or natural monument) from zoom 12 instead of 14 (with MAGNIFY=2 they appear from zoom 13)
s2_path = mapnik_dir / "styles-otm" / "symbols-2.xml"
s2, n = re.subn(r"&maxscale_zoom14;(\s*&minscale_zoom17;\s*<Filter>\(\(\[natural\] = 'tree'\))", r"&maxscale_zoom12;\1", s2_path.read_text())
if n != 2:
    sys.exit(f"style patch failed (notable trees zoom): {n} matches instead of 2")
s2_path.write_text(s2)
print("patched: notable single trees from zoom 12")

# ---------------------------------------------------------------- trail and minor road names from zoom 14
# (OpenTopoMap: from zoom 16). "spacing" repeats the name along long ways.
rn_path = mapnik_dir / "styles-otm" / "road-names-text.xml"
rn = rn_path.read_text()
TRAILS = " or ".join(f"[highway] = '{h}'" for h in (
    "path", "footway", "bridleway", "track", "cycleway", "steps",
    "tertiary", "tertiary_link", "unclassified", "residential", "service", "living_street", "road"))
trail_rules = "".join(
    f"<Rule>&maxscale_zoom{z};&minscale_zoom{z};<Filter>{TRAILS}</Filter>"
    f'<TextSymbolizer fontset-name="sans-condensed" size="{size}" fill="black" halo-radius="1.5" halo-fill="rgba(255,255,255,0.8)" '
    f'repeat-distance="{rep}" spacing="{rep}" placement="line" max-char-angle-delta="40">[name]</TextSymbolizer></Rule>'
    for z, size, rep in (((13, 8, 350),) if EARLY else ()) + ((14, 9, 300), (15, 10, 220)))
if "<!-- zoom 15 -->" not in rn:
    sys.exit("style patch failed (trail names): original text not found")
rn_path.write_text(rn.replace("<!-- zoom 15 -->", trail_rules + "\n\t<!-- zoom 15 -->", 1))
print("patched: trail names from zoom 14")

# ---------------------------------------------------------------- forest: only green, no tree symbols
for name in ("landuse.xml", "landuse-over-hillshade.xml"):
    fp = mapnik_dir / "styles-otm" / name
    # the forest patterns contain the green background: replace them with a plain fill of the same colour
    # (landuse.xml); the faint second pattern over the hillshade is dropped
    plain = '<PolygonSymbolizer fill="#b7d97b" />' if name == "landuse.xml" else ""
    t, n = re.subn(r'<PolygonPatternSymbolizer file="symbols-otm/forest[^"]*"[^>]*/>', plain, fp.read_text())
    if n != 3:
        sys.exit(f"style patch failed (forest symbols in {name}): {n} instead of 3")
    fp.write_text(t)
print("patched: forest without tree symbols")

# ---------------------------------------------------------------- TASVEG vegetation instead of OSM forest (option)
# class A "Waldgefühl" (render/tasveg/klassen_waldtypen.csv), colours agreed with the user
TASVEG_COLOURS = {1: "#4F9A57",   # rainforest
                  2: "#82BC6A",   # wet forest over rainforest
                  3: "#B6D778",   # other wet forest
                  4: "#D6C468",   # dry eucalypt forest (light yellow-ochre)
                  5: "#9DBF57",   # other forest / swamp forest (like other wet forest, darker)
                  6: "#EDE8D2",   # open land / highland
                  7: "#F4F0E6",   # farmland (F codes except plantations and urban)
                  8: "#DCDDC6"}   # plantations
if TASVEG:
    # OSM forest, wood and scrub are no longer drawn (all other land use, water etc. stay)
    removed = 0
    for name in ("landuse.xml", "landuse-over-hillshade.xml"):
        fp = mapnik_dir / "styles-otm" / name
        t = fp.read_text()

        def drop(m):
            global removed
            f = re.search(r"<Filter>(.*?)</Filter>", m.group(0), re.S)
            if f and ("'forest'" in f.group(1) or "[natural] = 'scrub'" in f.group(1)):
                removed += 1
                return ""
            return m.group(0)
        fp.write_text(re.sub(r"<Rule>.*?</Rule>", drop, t, flags=re.S))
    lz = mapnik_dir / "styles-otm" / "landuse-lowzoom.xml"   # low zoom table holds forest only
    t, n = re.subn(r'<PolygonSymbolizer fill="#b9d984" />', "", lz.read_text())
    if removed < 8 or n != 1:
        sys.exit(f"style patch failed (OSM forest off): {removed} rules, {n} low zoom")
    lz.write_text(t)
    print(f"patched: OSM forest/scrub off ({removed} rules)")

    def fills(zfrom, zto):
        lim = f"&maxscale_zoom{zfrom};" + (f"&minscale_zoom{zto};" if zto else "")
        return "".join(f'<Rule>{lim}<Filter>[cls_a] = {k}</Filter><PolygonSymbolizer fill="{c}" gamma="0.5"/></Rule>'
                       for k, c in TASVEG_COLOURS.items())

    TV_STYLE = f"""<Style name="own-tasveg-low">{fills(5, 11)}</Style>
<Style name="own-tasveg">{fills(12, None)}
<Rule>&maxscale_zoom12;<Filter>[forest_str] = 'Woodland'</Filter>
<PolygonPatternSymbolizer file="symbols-otm/tasveg_woodland_hatch.svg" alignment="global"/></Rule>
</Style>
<Style name="own-tasveg-trees">
<Rule>&maxscale_zoom15;<PointSymbolizer file="symbols-otm/tasveg_notable_tree.svg" allow-overlap="true"/></Rule>
</Style>"""
    tv_layers = "\n".join([
        TV_STYLE,
        layer("own-tasveg-low", ["own-tasveg-low"], "(SELECT way, cls_a FROM tasveg_low) AS tv"),
        layer("own-tasveg", ["own-tasveg"], "(SELECT way, cls_a, forest_str FROM tasveg) AS tv"),
    ])
    # above OSM land use, below the hillshade and everything else
    xml = patch("\n\t&hillshade;", "\n" + tv_layers + "\n\t&hillshade;", "TASVEG vegetation layer")
    trees = layer("own-tasveg-trees", ["own-tasveg-trees"], "(SELECT way, area, notable_tr FROM tasveg_notable) AS tvt")
    xml = patch("</Map>", trees + "\n</Map>", "TASVEG notable trees")

# ---------------------------------------------------------------- own points: giant trees (render/pois/tasmanien_baeume.csv)
# golden star from zoom 9, name from zoom 12 (with MAGNIFY=2 shown from 10 and 13)
import csv as _csv
trees_out = mapnik_dir / "own_big_trees.csv"
with open(here / "pois" / "tasmanien_baeume.csv", encoding="utf-8-sig") as f_in, open(trees_out, "w", newline="", encoding="utf-8") as f_out:
    w = _csv.writer(f_out)
    w.writerow(["name", "lat", "lon"])
    for r in _csv.DictReader(f_in, delimiter=";"):
        lat, lon = (float(v) for v in r["Koordinaten"].split(","))
        w.writerow([r["Name"].strip(), lat, lon])
BIG_TREES = f"""<Style name="own-big-trees">
<Rule>&maxscale_zoom9;<PointSymbolizer file="symbols-otm/big_tree_star.svg" allow-overlap="true"/></Rule>
<Rule>&maxscale_zoom12;<TextSymbolizer fontset-name="sans-condensed-bold" size="9" fill="#5a3d00" halo-radius="1.5" halo-fill="rgba(255,255,255,0.85)"
 dy="11" wrap-width="80" allow-overlap="false">[name]</TextSymbolizer></Rule>
</Style>
<Layer name="own-big-trees" srs="+proj=longlat +datum=WGS84 +no_defs"><StyleName>own-big-trees</StyleName><Datasource>
<Parameter name="type">csv</Parameter><Parameter name="file">{trees_out}</Parameter></Datasource></Layer>
"""
xml = patch("</Map>", BIG_TREES + "</Map>", "giant trees (golden stars)")

# ---------------------------------------------------------------- 5+6) camp sites, locked gates (on top)
CAMPS_SQL = one_line("""(SELECT way, name FROM planet_osm_point WHERE tourism = 'camp_site'
  UNION ALL SELECT ST_PointOnSurface(way) AS way, name FROM planet_osm_polygon WHERE tourism = 'camp_site') AS camps""")
GATES_SQL = one_line("""(SELECT way FROM planet_osm_point
  WHERE barrier IN ('gate','lift_gate','swing_gate','chain','bar') AND locked = 'yes') AS lockedgates""")
TOP = f"""<Style name="own-camps">
<Rule>&maxscale_zoom11;&minscale_zoom12;<PointSymbolizer file="symbols-otm/camp_highlight.svg" transform="scale(0.75)" allow-overlap="true"/></Rule>
<Rule>&maxscale_zoom13;<PointSymbolizer file="symbols-otm/camp_highlight.svg" allow-overlap="true"/>
<TextSymbolizer fontset-name="sans-condensed-bold" size="10" fill="#1b7f3b" halo-radius="1.5" halo-fill="rgba(255,255,255,0.9)" dy="14" wrap-width="90">[name]</TextSymbolizer></Rule>
</Style>
<Style name="own-gates">
<Rule>&maxscale_zoom13;&minscale_zoom14;<PointSymbolizer file="symbols-otm/gate_locked.svg" transform="scale(0.8)" allow-overlap="true"/></Rule>
<Rule>&maxscale_zoom15;<PointSymbolizer file="symbols-otm/gate_locked.svg" allow-overlap="true"/></Rule>
</Style>
{layer("own-camps", ["own-camps"], CAMPS_SQL)}
{layer("own-gates", ["own-gates"], GATES_SQL)}
{layer("own-4wd", ["own-4wd"], FOURWD_SQL)}
"""
xml = patch("</Map>", TOP + "</Map>", "camp sites and locked gates on top")

xml_path.write_text(xml)
