"""Back-solve plate thickness from the mass printed on the drawing.

A single-view drawing of a flat part usually states its weight in the title
block but never its thickness. Once the DXF gives the net area, the thickness
follows from mass / (area * density) -- that single number is what unblocks
modelling, and it is checkable: rebuild with it and the mass must come back.

    python estimate_thickness.py part.dxf 4.87
    python estimate_thickness.py part.dxf 4.87 --density 7.85 --tolerance 0.03

Prints the net area, the computed thickness, and the nearest stock sizes. Pick
the candidate whose own mass lands inside --tolerance of the stated mass; if
none does, the geometry extraction is wrong, not the thickness.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxf_geom import read_pairs, split_entities
from part_from_dxf import pick_part, merge_holes

# g/mm3 -- 6061 aluminium, mild steel, stainless, brass, titanium
DENSITIES = {
    "aluminium": 0.00270,
    "steel": 0.00785,
    "stainless": 0.00793,
    "brass": 0.00850,
    "titanium": 0.00443,
}

# plate stock actually sold in China, rough sequence
STOCK = [0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 6.35, 8.0,
         10.0, 12.0, 14.0, 15.0, 16.0, 18.0, 20.0, 22.0, 25.0, 30.0, 40.0, 50.0]


def net_area_mm2(dxf_path):
    ents = split_entities(read_pairs(dxf_path))
    outer, inner, holes, _ = pick_part(ents)
    area = abs(outer["area"])
    for loop in inner:
        area -= abs(loop["area"])
    # concentric circles are one hole; subtracting both inflates the hole area
    # and makes the back-solved thickness come out high
    groups = merge_holes(holes)
    for h in groups:
        area -= math.pi * h["bore"] ** 2
    ring = sum(math.pi * (h["rim"] ** 2 - h["bore"] ** 2) for h in groups)
    return area, outer, inner, groups, ring


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf", help="part DXF, i.e. the one part_from_dxf.py wrote")
    ap.add_argument("mass", type=float, help="mass printed on the drawing, kg")
    ap.add_argument("--density", type=float, default=None,
                    help="g/mm3; or pass --material aluminium|steel|...")
    ap.add_argument("--material", choices=sorted(DENSITIES), default="aluminium")
    ap.add_argument("--tolerance", type=float, default=0.02,
                    help="accepted relative mass error, default 2%%")
    ap.add_argument("--counterbore", type=float, default=0.0,
                    help="counterbore depth mm, if the drawing calls one out; "
                         "it eats extra material beyond the through hole")
    a = ap.parse_args()

    rho = a.density if a.density else DENSITIES[a.material]
    area, outer, inner, groups, ring = net_area_mm2(a.dxf)

    volume = a.mass * 1000.0 / rho        # kg -> g -> mm3
    # volume = area*t - ring*cb  =>  t = (volume + ring*cb) / area
    t = (volume + ring * a.counterbore) / area

    print("net area      %.2f mm2  (%d hole positions)" % (area, len(groups)))
    print("  outer       %.1f x %.1f" % (
        max(p[0] for p in outer["pts"]) - min(p[0] for p in outer["pts"]),
        max(p[1] for p in outer["pts"]) - min(p[1] for p in outer["pts"])))
    print("  windows     %d   holes %d  (counterbores %d)"
          % (len(inner), len(groups), sum(1 for h in groups if h["n"] > 1)))
    print("density       %.5f g/mm3 (%s)" % (rho, a.material if not a.density else "manual"))
    print("volume        %.1f mm3  from %.2f kg" % (volume, a.mass))
    print("thickness     %.3f mm   <-- computed" % t)
    print("-" * 58)   # not a bare print(): PowerShell swallows blank lines

    print("candidates (closest stock sizes, mass they would give):")
    near = sorted(STOCK, key=lambda s: abs(s - t))[:4]
    ok = []
    for s in sorted(near):
        m = (area * s - ring * a.counterbore) * rho / 1000.0
        err = (m - a.mass) / a.mass
        flag = "OK" if abs(err) <= a.tolerance else ""
        if flag:
            ok.append(s)
        print("  t=%-6.2f -> %.4f kg  (%+.2f%%) %s" % (s, m, err * 100, flag))
    print("-" * 58)

    if ok:
        print("RESULT: use thickness %.2f mm (mass matches within %.0f%%)"
              % (ok[0], a.tolerance * 100))
    else:
        print("RESULT: none of the stock sizes reproduces %.2f kg." % a.mass)
        print("        Computed t=%.3f mm matches no stock size." % t)
        print("        Before guessing, re-check the geometry extraction: a missed")
        print("        window or a wrongly-kept frame loop moves the area, and the")
        print("        thickness error is exactly that area error inverted.")


if __name__ == "__main__":
    main()
