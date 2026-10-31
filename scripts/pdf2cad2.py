#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PDF drawing -> AutoCAD replay plan (v2).

Key differences from v1:
  * coordinates are converted to CAD mm up-front (X = x*S, Y = (page_h - y)*S)
  * arcs that are part of a longer path are kept INSIDE the polyline as bulge
    values, so a part outline stays ONE closed polyline instead of being
    chopped into lines; only truly closed rings become CIRCLE entities
"""
import sys, os, json, math, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from pyml import pymupdf

SHORT = 2.5
MIN_RUN = 6
FIT_RMS = 0.06
W_OUTLINE = 0.992
W_TOL = 0.1
TAU = 2.0 * math.pi


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def fit_circle(p):
    n = len(p)
    if n < MIN_RUN:
        return None
    sx = sy = sxx = syy = sxy = sxz = syz = sz = 0.0
    for x, y in p:
        z = x * x + y * y
        sx += x; sy += y; sxz += x * z; syz += y * z
        sxx += x * x; syy += y * y; sxy += x * y; sz += z
    M = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
    rhs = [-sxz, -syz, -sz]

    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    D = det3(M)
    if abs(D) < 1e-12:
        return None
    sol = []
    for col in range(3):
        m = [row[:] for row in M]
        for r in range(3):
            m[r][col] = rhs[r]
        sol.append(det3(m) / D)
    A, B, C = sol
    cx, cy = -A / 2.0, -B / 2.0
    r2 = cx * cx + cy * cy - C
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    rms = math.sqrt(sum((dist((x, y), (cx, cy)) - r) ** 2 for x, y in p) / n)
    return cx, cy, r, rms


def build_chains(dr, tol=0.6):
    """Rebuild continuous chains from a PDF path's segments.

    PDF line direction is arbitrary (some run A->B, some B->A), so matching
    'previous end == next start' alone shreds the path. Here each new segment
    is accepted if ANY of its endpoints lands within tol of the current tail,
    and it is reversed when needed.
    """
    segs = []
    for it in dr.get("items", []):
        k = it[0]
        if k == "l":
            segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
        elif k == "re":
            r = it[1]
            c = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
            for q in range(4):
                segs.append((c[q], c[(q + 1) % 4]))
        elif k == "qu":
            q = it[1]
            try:
                c = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
                for u in range(4):
                    segs.append((c[u], c[(u + 1) % 4]))
            except Exception:
                pass
    if not segs:
        return []

    n = len(segs)
    used = [False] * n
    chains = []
    for s0 in range(n):
        if used[s0]:
            continue
        used[s0] = True
        chain = [segs[s0][0], segs[s0][1]]
        while True:
            tail = chain[-1]
            best = -1
            bestd = tol
            bestrev = False
            for j in range(n):
                if used[j]:
                    continue
                a, b = segs[j]
                d = dist(tail, a)
                if d < bestd:
                    bestd = d; best = j; bestrev = False
                d = dist(tail, b)
                if d < bestd:
                    bestd = d; best = j; bestrev = True
            if best < 0:
                break
            used[best] = True
            a, b = segs[best]
            chain.append(a if bestrev else b)
        chains.append(chain)
    return chains


def find_runs(pts):
    """Return list of (i, j, cx, cy, r) runs of short segments fitting a circle."""
    out = []
    n = len(pts)
    i = 0
    while i < n - 1:
        if dist(pts[i], pts[i + 1]) < SHORT:
            j = i
            while j < n - 1 and dist(pts[j], pts[j + 1]) < SHORT:
                j += 1
            if j - i >= MIN_RUN:
                f = fit_circle(pts[i:j + 1])
                if f and f[3] < FIT_RMS and f[2] > 0.4:
                    out.append((i, j, f[0], f[1], f[2]))
            i = j
        else:
            i += 1
    return out


def arc_theta(cad_pts, cx, cy):
    """Signed sweep angle (radians) of a point run around a centre, in CAD coords."""
    ang = [math.atan2(p[1] - cy, p[0] - cx) for p in cad_pts]
    t = 0.0
    for k in range(len(ang) - 1):
        d = ang[k + 1] - ang[k]
        while d > math.pi:
            d -= TAU
        while d < -math.pi:
            d += TAU
        t += d
    return t


def classify(dr):
    w = dr.get("width")
    if w is None:
        return "FILL"
    if abs(float(w) - W_OUTLINE) < W_TOL:
        return "OUTLINE"
    return "THIN"


# the sheet carries three text zones:
#   title block  (bottom right) -- names, dates, part no, material, weight
#   tech notes   (bottom left)  -- general tolerance boilerplate
#   the views    (everywhere above) -- dimensions, hole callouts
# to rebuild the part in 3D only the third zone carries information, so the
# first two are cut away wholesale by their y band.
TITLE_BAND_Y = 250.0


def filter_texts(texts, mode):
    if mode == "all":
        return texts, 0
    keep, dropped = [], 0
    for t in texts:
        s = t["t"]
        if t["p"][1] < TITLE_BAND_Y:
            dropped += 1          # title block / tech notes
            continue
        if "秘密" in s or "\u2605" in s:
            dropped += 1          # confidentiality stamp
            continue
        keep.append(t)
    return keep, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=None)
    ap.add_argument("--part-width", type=float, default=700.0)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--texts", choices=["all", "dim"], default="all",
                    help="'dim' keeps only annotation text, dropping the "
                         "title block and technical-requirements block")
    a = ap.parse_args()

    doc = pymupdf.open(a.pdf)
    page = doc[a.page - 1]
    ph = page.rect.height
    drawings = page.get_drawings()

    scale = a.scale
    if scale is None:
        pw = page.rect.width
        cands = []
        for dr in drawings:
            if classify(dr) != "OUTLINE":
                continue
            xs, ys = [], []
            for it in dr.get("items", []):
                if it[0] == "l":
                    xs += [it[1].x, it[2].x]
                    ys += [it[1].y, it[2].y]
            if len(xs) < 20:
                continue
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if w > pw * 0.8 or w < 20 or h < 20:
                continue
            cands.append((w * h, w, h))
        cands.sort(reverse=True)
        scale = (a.part_width / cands[0][1]) if cands else 1.0
    print("scale = %.6f mm/pt" % scale)

    def to_cad(p):
        return (p[0] * scale, (ph - p[1]) * scale)

    plan = {"file": a.pdf, "scale": scale, "page_h": ph,
            "polylines": [], "circles": [], "texts": []}
    stats = {"circles": 0, "polylines": 0, "arcs": 0}

    for dr in drawings:
        layer = classify(dr)
        for sub in build_chains(dr):
            if len(sub) < 2:
                continue
            runs = find_runs(sub)
            # a run covering the whole closed subpath -> standalone circle
            whole_run = None
            for (i, j, cx, cy, r) in runs:
                if i == 0 and j >= len(sub) - 1 and dist(sub[0], sub[-1]) < 0.05:
                    whole_run = (i, j, cx, cy, r)
                    break
            if whole_run:
                _, _, cx, cy, r = whole_run
                c = to_cad((cx, cy))
                plan["circles"].append({"c": [round(c[0], 3), round(c[1], 3)],
                                        "r": round(r * scale, 3), "layer": layer})
                stats["circles"] += 1
                continue

            runs = find_runs(sub)
            pieces = []
            k = 0
            nseg = len(sub) - 1
            while k < nseg:
                hit = None
                for (i, j, cx, cy, r) in runs:
                    if i <= k < j:
                        hit = (i, j, cx, cy, r)
                        break
                if hit:
                    i, j, cx, cy, r = hit
                    p1 = to_cad(sub[i])
                    p2 = to_cad(sub[j])
                    cc = to_cad((cx, cy))
                    th = arc_theta([to_cad(p) for p in sub[i:j + 1]], cc[0], cc[1])
                    if abs(th) > 0.02:
                        pieces.append(("arc", p1, p2, math.tan(th / 4.0)))
                        stats["arcs"] += 1
                    else:
                        pieces.append(("line", p1, p2, 0.0))
                    k = j
                else:
                    pieces.append(("line", to_cad(sub[k]), to_cad(sub[k + 1]), 0.0))
                    k += 1

            if not pieces:
                continue
            pts = [pieces[0][1]]
            bul = []
            for pc in pieces:
                pts.append(pc[2])
                bul.append(pc[3])
            closed = dist(pts[0], pts[-1]) < 0.05
            if closed and len(pts) > 2:
                # drop duplicated closing point: len(pts) becomes len(bul), which
                # is exactly what a closed LWPOLYLINE expects (one bulge per point)
                pts = pts[:-1]
            plan["polylines"].append({
                "pts": [[round(x, 3), round(y, 3)] for x, y in pts],
                "bul": [round(b, 6) for b in bul],
                "closed": bool(closed),
                "layer": layer})
            stats["polylines"] += 1

    skipped_wm = 0
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            d = line.get("dir", (1, 0))
            ang = math.degrees(math.atan2(d[1], d[0]))
            horizontal = abs(ang) < 1
            is_diagonal = abs(ang) > 1 and abs(abs(ang) - 90) > 1
            for span in line.get("spans", []):
                chars = span.get("chars", [])
                if not chars:
                    continue
                t = "".join(ch.get("c", "") for ch in chars).strip()
                if not t:
                    continue
                # watermark: grey 45-degree stamp, not drawing content
                if int(span.get("color", 0)) != 0 or is_diagonal:
                    skipped_wm += 1
                    continue
                sz = float(span.get("size", 0))
                # real rendered width: sum per-glyph boxes. For vertical text the
                # advance runs along Y, so the box height is the glyph width.
                wsum = 0.0
                for ch in chars:
                    b = ch.get("bbox", [0, 0, 0, 0])
                    wsum += (b[2] - b[0]) if horizontal else (b[3] - b[1])
                # compare against what CAD would naturally draw: CJK is 1.0 em,
                # ASCII is roughly 0.5 em in SimSun. Using the glyph box alone
                # makes narrow glyphs like "1" collapse.
                expected = 0.0
                for ch in chars:
                    o = ord(ch.get("c", " "))
                    if (0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F
                            or 0xFF00 <= o <= 0xFFEF or o in (0x2605, 0x00D7, 0x00B1)):
                        expected += 1.0
                    else:
                        expected += 0.5
                expected *= sz
                wf = (wsum / expected) if expected > 0 else 1.0
                wf = min(max(wf, 0.3), 1.6)

                # PDF "size" is the em box; SimSun CJK ink height is ~0.88 em.
                # AutoCAD's Height IS the glyph height, so scale it down and
                # compensate in the width factor to keep the advance unchanged.
                GLYPH = 0.88
                wf = min(max(wf / GLYPH, 0.3), 1.8)

                bb = span.get("bbox", [0, 0, 0, 0])
                org = span.get("origin", (bb[0], bb[3]))
                c = to_cad((org[0], org[1]))
                rot = 0.0 if horizontal else (math.pi / 2.0)
                plan["texts"].append({"t": t,
                                      "p": [round(c[0], 3), round(c[1], 3)],
                                      "h": round(sz * scale * 0.88, 2),
                                      "rot": round(rot, 4),
                                      "wf": round(wf, 3)})
    stats["watermark_skipped"] = skipped_wm

    plan["texts"], dropped_txt = filter_texts(plan["texts"], a.texts)
    stats["texts"] = len(plan["texts"])
    stats["texts_dropped"] = dropped_txt
    print("texts kept %d, dropped %d (mode=%s)"
          % (len(plan["texts"]), dropped_txt, a.texts))

    plan["stats"] = stats
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False))
    print("written:", a.out)


if __name__ == "__main__":
    main()
