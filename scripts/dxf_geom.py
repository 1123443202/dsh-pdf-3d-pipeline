"""Minimal ASCII DXF inspector / filter (no ezdxf needed).

Reports entity counts per (type, layer) and the bounding box, then can write a
filtered copy that keeps only the requested layers/entity types.
"""
import sys
from collections import Counter, defaultdict


def read_pairs(path):
    """Yield (code, value) pairs from an ASCII DXF."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    out = []
    for i in range(0, len(lines) - 1, 2):
        code = lines[i].strip()
        val = lines[i + 1]
        try:
            code = int(code)
        except ValueError:
            continue
        out.append((code, val.strip()))
    return out


def split_entities(pairs):
    """Split the ENTITIES section into [(type, [(code,val),...]), ...]."""
    ent_start = None
    for i, (c, v) in enumerate(pairs):
        if c == 2 and v == "ENTITIES":
            ent_start = i
            break
    if ent_start is None:
        return []
    ents = []
    cur = None
    i = ent_start
    while i < len(pairs):
        c, v = pairs[i]
        if c == 0:
            if v == "ENDSEC":
                if cur:
                    ents.append(cur)
                break
            if cur:
                ents.append(cur)
            cur = (v, [])
        elif cur is not None:
            cur[1].append((c, v))
        i += 1
    return [e for e in ents if e[0] not in ("SECTION", "ENDSEC")]


def bbox_of(ents):
    xs, ys = [], []
    for t, rec in ents:
        if t == "LINE":
            for c, v in rec:
                if c == 10:
                    xs.append(float(v))
                if c == 20:
                    ys.append(float(v))
        elif t == "LWPOLYLINE":
            for c, v in rec:
                if c == 10:
                    xs.append(float(v))
                if c == 20:
                    ys.append(float(v))
        elif t in ("CIRCLE", "ARC"):
            cx = cy = r = None
            for c, v in rec:
                if c == 10:
                    cx = float(v)
                if c == 20:
                    cy = float(v)
                if c == 40:
                    r = float(v)
            if cx is not None and r is not None:
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
        elif t == "TEXT":
            for c, v in rec:
                if c == 10:
                    xs.append(float(v))
                if c == 20:
                    ys.append(float(v))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def layer_of(rec):
    for c, v in rec:
        if c == 8:
            return v
    return "0"


def main():
    path = sys.argv[1]
    pairs = read_pairs(path)
    ents = split_entities(pairs)
    print("entities:", len(ents))
    cnt = Counter((t, layer_of(r)) for t, r in ents)
    for (t, lay), n in cnt.most_common():
        print(f"  {t:12s} layer={lay:16s} {n}")
    bb = bbox_of(ents)
    if bb:
        print("bbox  X %.2f..%.2f  (%.2f)   Y %.2f..%.2f  (%.2f)" % (
            bb[0], bb[2], bb[2] - bb[0], bb[1], bb[3], bb[3] - bb[1]))
    for t in ("LINE", "LWPOLYLINE", "CIRCLE", "ARC"):
        sub = [e for e in ents if e[0] == t]
        b = bbox_of(sub)
        if b:
            print("  %-10s bbox %.2f x %.2f" % (t, b[2] - b[0], b[3] - b[1]))

    # header units
    for i, (c, v) in enumerate(pairs):
        if v == "$INSUNITS":
            print("$INSUNITS =", pairs[i + 1][1])
            break


if __name__ == "__main__":
    main()
