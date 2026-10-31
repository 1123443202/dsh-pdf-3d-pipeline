"""Turn the part DXF into a segment list the SolidWorks driver can replay.

Every edge becomes either a line or a three-point arc (start, end, mid). The
mid point is derived from the DXF bulge (bulge = sagitta / half-chord), which
is exact for any included angle including 180 degrees — deriving it from the
two endpoints alone is what flips slotted holes inside out.
"""
import json
import math
import os
import sys

# resolve siblings from this file, not the caller's cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_geom import read_pairs, split_entities, layer_of
from part_from_dxf import loops_from, signed_area, point_in_poly, pick_part

SMALL_R = 5.0        # below this, flatten the arc: SolidWorks snapping eats it
FLAT_STEPS = 4       # segments per 90 degrees when flattening


def arc_mid(p1, p2, bulge):
    """Mid point of a bulged edge. bulge = tan(theta/4), signed (+ = CCW)."""
    x1, y1 = p1
    x2, y2 = p2
    c = math.hypot(x2 - x1, y2 - y1)
    if c < 1e-12:
        return None
    sag = bulge * c / 2.0
    # A positive bulge is a counter-clockwise arc, which bulges to the RIGHT of
    # p1->p2 (a CCW semicircle from (0,0) to (1,0) passes through (0.5,-0.5)).
    # Using the left normal here mirrors every arc and the contour self-
    # intersects, which SolidWorks then refuses to extrude.
    nx, ny = (y2 - y1) / c, -(x2 - x1) / c
    return [x1 + (x2 - x1) / 2.0 + nx * sag, y1 + (y2 - y1) / 2.0 + ny * sag]


def flatten_arc(p1, p2, bulge, steps=FLAT_STEPS):
    """Approximate a small-radius arc with a short polyline."""
    theta = 4.0 * math.atan(bulge)
    mid = arc_mid(p1, p2, bulge)
    if mid is None:
        return [[p1, p2]]
    # circumcentre of the three points
    (ax, ay), (bx, by), (cx, cy) = p1, p2, mid
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [[p1, p2]]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a1 = math.atan2(ay - uy, ax - ux)
    a2 = math.atan2(cy - uy, cx - ux)
    a3 = math.atan2(by - uy, bx - ux)
    # choose the sweep that passes through the arc mid point
    def norm(a):
        while a <= -math.pi:
            a += 2 * math.pi
        while a > math.pi:
            a -= 2 * math.pi
        return a
    sweep = norm(a3 - a1)
    if norm(a2 - a1) * sweep < 0:
        sweep = sweep - 2 * math.pi * (1 if sweep > 0 else -1)
    pts = []
    n = max(2, int(round(abs(sweep) / (math.pi / 2) * steps)))
    for i in range(n + 1):
        a = a1 + sweep * i / n
        pts.append([ux + r * math.cos(a), uy + r * math.sin(a)])
    return [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]


def build(path, depth):
    ents = split_entities(read_pairs(path))
    outer, inner, holes, _ = pick_part(ents)

    segs = []
    for gi, loop in enumerate([outer] + inner):
        pts = loop["pts"]
        bul = loop["bul"]
        n = len(pts)
        for i in range(n):
            p1 = pts[i]
            p2 = pts[(i + 1) % n]
            b = bul[i] if i < len(bul) else 0.0
            if abs(b) < 1e-12:
                segs.append({"t": "line", "a": p1, "b": p2, "g": gi})
                continue
            r = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / (2 * abs(math.sin(2 * math.atan(abs(b)))))
            if r < SMALL_R:
                for s in flatten_arc(p1, p2, b):
                    segs.append({"t": "line", "a": s[0], "b": s[1], "g": gi})
            else:
                m = arc_mid(p1, p2, b)
                segs.append({"t": "arc", "a": p1, "b": p2, "m": m, "g": gi})
    for h in holes:
        segs.append({"t": "circle", "c": list(h["c"]), "r": h["r"], "g": 100})

    xs = [p[0] for p in outer["pts"]]
    ys = [p[1] for p in outer["pts"]]
    ox, oy = min(xs), min(ys)
    for sg in segs:
        if sg["t"] == "circle":
            sg["c"] = [sg["c"][0] - ox, sg["c"][1] - oy]
        else:
            sg["a"] = [sg["a"][0] - ox, sg["a"][1] - oy]
            sg["b"] = [sg["b"][0] - ox, sg["b"][1] - oy]
            if sg["t"] == "arc":
                sg["m"] = [sg["m"][0] - ox, sg["m"][1] - oy]
    return {
        "depth_mm": depth,
        "origin": [0.0, 0.0],
        "segments": segs,
        "counts": {
            "line": sum(1 for s in segs if s["t"] == "line"),
            "arc": sum(1 for s in segs if s["t"] == "arc"),
            "circle": sum(1 for s in segs if s["t"] == "circle"),
        },
    }


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2]
    depth = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
    data = build(src, depth)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("wrote", dst, data["counts"])
