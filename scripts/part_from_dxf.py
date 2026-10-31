"""Area / volume check of the part loops found in the DXF, then emit a clean part DXF.

Bulges follow the DXF convention: bulge = tan(theta/4), positive = CCW.
"""
import math
import os
import sys

# resolve siblings from this file, not the caller's cwd: the skill is invoked
# from wherever the drawing happens to live
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_geom import read_pairs, split_entities, layer_of


def loops_from(rec):
    """Return (points, bulges) for one LWPOLYLINE."""
    pts, bul = [], []
    pending_bulge = 0.0
    for c, v in rec:
        if c == 10:
            if pts:
                bul.append(pending_bulge)
            pending_bulge = 0.0
            pts.append([float(v), None])
        elif c == 20 and pts and pts[-1][1] is None:
            pts[-1][1] = float(v)
        elif c == 42:
            pending_bulge = float(v)
    if pts:
        bul.append(pending_bulge)
    pts = [p for p in pts if p[1] is not None]
    bul = bul[: len(pts)]
    return pts, bul


def signed_area(pts, bul):
    """Shoelace for the polygon, plus the circular-segment correction for bulges."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    a *= 0.5
    # each bulged edge bulges outward from the chord: add the segment area
    for i, b in enumerate(bul):
        if abs(b) < 1e-12:
            continue
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        chord = math.hypot(x2 - x1, y2 - y1)
        if chord < 1e-12:
            continue
        theta = 4.0 * math.atan(abs(b))          # included angle
        r = chord / (2.0 * math.sin(theta / 2.0))
        seg = 0.5 * r * r * (theta - math.sin(theta))   # chord<->arc area
        a += seg if b > 0 else -seg
    return a


def point_in_poly(pt, pts):
    x, y = pt
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def pick_part(ents):
    """Classify the 0-OUTLINE entities that belong to the part, not the sheet.

    The sheet frame also encloses every hole, so "contains the most circles" is
    not enough: among the loops that contain them all, the part is the smallest.
    """
    loops, holes = [], []
    for idx, (t, rec) in enumerate(ents):
        lay = layer_of(rec)
        if lay != "0-OUTLINE":
            continue
        if t == "LWPOLYLINE":
            pts, bul = loops_from(rec)
            if len(pts) < 3:
                continue
            area = signed_area(pts, bul)
            if abs(area) < 1.0:          # open polyline / zero-area decoration
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            span = (max(xs) - min(xs), max(ys) - min(ys))
            loops.append({"pts": pts, "bul": bul, "area": area, "span": span, "idx": idx})
        elif t == "CIRCLE":
            cx = cy = r = None
            for c, v in rec:
                if c == 10:
                    cx = float(v)
                elif c == 20:
                    cy = float(v)
                elif c == 40:
                    r = float(v)
            holes.append({"c": (cx, cy), "r": r, "idx": idx})

    if not holes:
        raise SystemExit("no circles found on the part layer")

    candidates = []
    for l in loops:
        hits = sum(1 for h in holes if point_in_poly(h["c"], l["pts"]))
        candidates.append((hits, abs(l["area"]), l))
    best = max(c[0] for c in candidates)
    good = [c for c in candidates if c[0] == best]
    outer = min(good, key=lambda c: c[1])[2]

    inner = []
    for l in loops:
        if l is outer:
            continue
        cx = sum(p[0] for p in l["pts"]) / len(l["pts"])
        cy = sum(p[1] for p in l["pts"]) / len(l["pts"])
        if point_in_poly((cx, cy), outer["pts"]) and abs(l["area"]) < abs(outer["area"]):
            inner.append(l)

    keep_holes = [h for h in holes if point_in_poly(h["c"], outer["pts"])]
    return outer, inner, keep_holes, []



def merge_holes(holes, tol=0.01):
    """Concentric circles are ONE hole, not several.

    A counterbore is drawn as phi11 over phi6.6 on the same centre. Summing
    both areas double-counts the bore and shrinks the theoretical volume, so
    the model then looks "too heavy" against a baseline that was never right.
    Each group collapses to (rim radius, bore radius).
    """
    groups = []
    for h in holes:
        for g in groups:
            if (abs(g[0]["c"][0] - h["c"][0]) < tol
                    and abs(g[0]["c"][1] - h["c"][1]) < tol):
                g.append(h)
                break
        else:
            groups.append([h])
    out = []
    for g in groups:
        rim = max(g, key=lambda x: x["r"])
        bore = min(g, key=lambda x: x["r"])
        out.append({"c": rim["c"], "rim": rim["r"], "bore": bore["r"], "n": len(g)})
    return out


def main():
    path = sys.argv[1]
    depth = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    out = sys.argv[3] if len(sys.argv) > 3 else None
    cb_depth = 0.0
    for i, a in enumerate(sys.argv):
        if a == "--counterbore" and i + 1 < len(sys.argv):
            cb_depth = float(sys.argv[i + 1])

    ents = split_entities(read_pairs(path))
    outer, inner, holes, guides = pick_part(ents)

    a_out = abs(outer["area"])
    a_in = sum(abs(l["area"]) for l in inner)
    hg = merge_holes(holes)
    a_bore = sum(math.pi * h["bore"] ** 2 for h in hg)
    a_rim = sum(math.pi * h["rim"] ** 2 for h in hg)
    a_cb = a_rim - a_bore                      # extra ring only the pockets eat
    n_cb = sum(1 for h in hg if h["n"] > 1)

    # solid volume: through holes for the full depth, counterbores for cb_depth
    vol = (a_out - a_in - a_bore) * depth - a_cb * cb_depth
    net = a_out - a_in - a_rim                 # footprint area, no double count

    print("outer loop  %.1f x %.1f  area %.2f mm2" % (outer["span"][0], outer["span"][1], a_out))
    for l in inner:
        print("  window    %.1f x %.1f  area %.2f" % (l["span"][0], l["span"][1], abs(l["area"])))
    print("holes %d circles -> %d positions (%d with counterbore)"
          % (len(holes), len(hg), n_cb))
    print("  through bores total %.2f mm2   counterbore rings %.2f mm2" % (a_bore, a_cb))
    print("net area %.2f mm2 (footprint)   solid volume = %.1f mm3   mass(6061) = %.3f kg"
          % (net, vol, vol * 2.70e-6))
    if cb_depth > 0 and n_cb:
        print("  volume accounts for %d counterbores, %.2f mm deep" % (n_cb, cb_depth))
    elif n_cb:
        print("  NOTE: %d counterbores found but no --counterbore depth given;" % n_cb)
        print("        volume above assumes they are through holes (it is an upper bound).")

    if not out:
        return

    # ---- emit a clean part DXF by slicing the original file ---------------
    # Hand-written DXF is rejected silently by the SolidWorks importer (it
    # returns True and imports nothing) because it has no layer table. Keeping
    # the original HEADER/TABLES and only rewriting the ENTITIES section does
    # import, so the chosen entities are re-emitted verbatim.
    pairs = read_pairs(path)
    ent_at = None
    for i in range(len(pairs) - 1):
        if pairs[i] == (0, "SECTION") and pairs[i + 1] == (2, "ENTITIES"):
            ent_at = i
            break
    if ent_at is None:
        raise SystemExit("ENTITIES section not found")

    keep = {outer["idx"]}
    for l in inner:
        keep.add(l["idx"])
    for h in holes:
        keep.add(h["idx"])

    out_pairs = list(pairs[: ent_at + 2])
    for idx, (t, rec) in enumerate(ents):
        if idx not in keep:
            continue
        out_pairs.append((0, t))
        out_pairs.extend(rec)
    out_pairs.append((0, "ENDSEC"))
    out_pairs.append((0, "EOF"))

    with open(out, "w", encoding="utf-8", newline="\r\n") as f:
        for c, v in out_pairs:
            f.write("%d\n%s\n" % (c, v))
    print("wrote %s (%d entities)" % (out, len(keep)))



if __name__ == "__main__":
    main()
