# -*- coding: utf-8 -*-
"""把图纸 PDF 里的「图注」读成结构化孔表 -> drawing_spec.json

为什么需要这一步（血的教训）：
    DWG 只记录「已经画出来的东西」，图注才记录「要求的东西」，两者会不一致。
    本零件有 16 个孔的 ⌴φ11▽6.8 只写在图注里，DWG 里只有一圈 φ6.6 圆，
    任何"按几何建模"的流程都必然漏掉这一整面的沉孔。
    所以验收基准必须是图注，不是几何。

符号在 PDF 里不是文字，是矢量线，只能按形状认：
    φ  = 约 49 段线围成的闭环（宽约 6.9、高约 8.3，高>宽因为有斜杠）
    ⌴  = 3 段线组成的开口 U（宽约 16、高约 8）
    ▽  = 4 段线：一条横线 + 一个朝下的 V（约 8×8）

读不出、读不懂的都进 unparsed / warnings，并以非零码退出——
宁可报错，也不要静默漏掉一条图注。

用法：
    python drawing_spec.py 图纸.pdf [drawing_spec.json]
"""
import sys
import os
import re
import json

try:
    import pymupdf
except ImportError:                                    # 老版本只有 fitz
    try:
        import fitz as pymupdf
    except ImportError:                                # 侧车依赖目录，按 PYMUPDF_PATH 等位置找
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from pyml import pymupdf

DIA, DEPTH, CBORE = "Ø", "▽", "⌴"
SYMCHAR = {DIA: "Ø", DEPTH: "▽", CBORE: "⌴"}


# ---------------------------------------------------------------- 符号识别
def _ends(item):
    """取一条 'l' 的两个端点。"""
    p = [q for q in item[1:] if hasattr(q, "x")]
    return (p[0], p[-1]) if len(p) >= 2 else None


def classify(d):
    """把一个矢量路径判成 φ / ⌴ / ▽，认不出返回 None。"""
    r = pymupdf.Rect(d["rect"])
    w, h = r.width, r.height
    items = d["items"]
    n = len(items)

    # φ：多段线围成的闭环，高略大于宽
    if n >= 30 and 5.0 <= w <= 9.5 and 6.0 <= h <= 11.0:
        return DIA

    segs = [s for s in (_ends(i) for i in items) if s]

    # ⌴：两条竖线 + 一条底横线，开口朝上
    if n == 3 and 12.0 <= w <= 20.0 and 5.5 <= h <= 9.5 and len(segs) == 3:
        vert = [s for s in segs if abs(s[0].x - s[1].x) < 0.3 and abs(s[1].y - s[0].y) > h * 0.55]
        horz = [s for s in segs if abs(s[0].y - s[1].y) < 0.3 and abs(s[1].x - s[0].x) > w * 0.55]
        if len(vert) == 2 and len(horz) == 1:
            return CBORE

    # ▽：顶部长横线 + 一个收在底部中心的 V
    if n == 4 and 6.0 <= w <= 9.5 and 6.0 <= h <= 9.5 and len(segs) == 4:
        horz = [s for s in segs if abs(s[0].y - s[1].y) < 0.3 and abs(s[1].x - s[0].x) > w * 0.7]
        tip = [s for s in segs for p in s
               if abs(p.y - r.y1) < 0.6 and abs(p.x - (r.x0 + w / 2.0)) < w * 0.35]
        if horz and tip:
            return DEPTH
    return None


# ---------------------------------------------------------------- 取词
def page_tokens(page):
    """文字词 + 符号，统一成 {x,y,h,s}，按阅读顺序可排序的 token 列表。"""
    rotated = set()
    for b in page.get_text("dict").get("blocks", []):
        d = b.get("dir")
        if d and abs(d[0] - 1.0) > 1e-3:      # 水印是旋转的，整块丢掉
            rotated.add(b.get("number"))

    toks = []
    for x0, y0, x1, y1, txt, bno, _l, _w in page.get_text("words"):
        if bno in rotated:
            continue
        if not txt.strip():
            continue
        # 水印是斜着印的整串编号，框比字高一个数量级，按高度再兜一次
        if "DTP" in txt or "秘密" in txt or "侯永刚" in txt:
            continue
        if (y1 - y0) > 22.0:
            continue
        toks.append({"x": x0, "x1": x1, "y": (y0 + y1) / 2.0, "h": y1 - y0, "s": txt})

    nsym = 0
    for d in page.get_drawings():
        k = classify(d)
        if not k:
            continue
        r = pymupdf.Rect(d["rect"])
        toks.append({"x": r.x0, "x1": r.x1, "y": (r.y0 + r.y1) / 2.0,
                     "h": r.height, "s": SYMCHAR[k], "sym": True})
        nsym += 1
    return toks, nsym


def _x1(t):
    return t.get("x1", t["x"] + 0.55 * t["h"] * len(t["s"]))


def split_lines(toks):
    """先只按文字词聚行（字号一致，y 才靠得住），再把符号挂到最近的一行。

    符号的框比文字高（φ 8.3、▽ 7.9 vs 文字 12.6 的下缘），直接参与聚行会把
    两行图注粘成一行——那正是第一版脚本读不出沉孔的原因。
    """
    texts = [t for t in toks if not t.get("sym")]
    syms = [t for t in toks if t.get("sym")]
    if not texts:
        return []
    hs = sorted(t["h"] for t in texts)
    th = hs[len(hs) // 2]

    texts.sort(key=lambda t: (t["y"], t["x"]))
    # 以行首为基准判断，不能让 y 一路"接力"往上飘——否则 135.6 的行会吞掉
    # 143.2、149.8 上别的标注，把两行图注粘成一行。
    lines, cur, anchor = [], [texts[0]], texts[0]["y"]
    for t in texts[1:]:
        if abs(t["y"] - anchor) <= 0.55 * th:
            cur.append(t)
        else:
            lines.append(cur)
            cur, anchor = [t], t["y"]
    lines.append(cur)

    for s in syms:
        best, score = None, 1e9
        for i, ln in enumerate(lines):
            ly = sum(q["y"] for q in ln) / float(len(ln))
            dy = abs(s["y"] - ly)
            if dy > 0.85 * th:
                continue
            dx = min(abs(s["x"] - q["x1"]) if q["x"] < s["x"] else abs(s["x"] - q["x"]) for q in ln)
            if dx > 60:
                continue
            if dy * 10 + dx < score:
                score, best = dy * 10 + dx, i
        if best is None:
            lines.append([s])
        else:
            lines[best].append(s)

    frags = []
    for ln in lines:
        ln.sort(key=lambda q: q["x"])
        cur = [ln[0]]
        for t in ln[1:]:
            if t["x"] - _x1(cur[-1]) > 26.0:      # 同一基线上的两个独立文字块
                frags.append(cur)
                cur = [t]
            else:
                cur.append(t)
        frags.append(cur)
    return frags


def frag_text(fr):
    out = []
    for t in fr:
        out.append(t["s"])
    return " ".join(out)


def frag_bbox(fr):
    x0 = min(t["x"] for t in fr)
    x1 = max(t["x"] for t in fr)
    y = sum(t["y"] for t in fr) / len(fr)
    return x0, x1, y


# ---------------------------------------------------------------- 解析
RE_COUNTED = re.compile(r"^(\d+)\s*[xX×]\s*[ØφΦ∅]")
RE_DIA = re.compile(r"[ØφΦ∅]\s*(\d+(?:\.\d+)?)")
RE_SLOT = re.compile(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)")
RE_FILLET = re.compile(r"(\d+)\s*[xX×]\s*R\s*(\d+(?:\.\d+)?)")


def parse_callout(text):
    """解析一条孔图注：`8 x Ø6.6 完全贯穿` / `⌴Ø11 ▽6.8` / `反面` / `▽10`。"""
    out = {}
    m = RE_COUNTED.search(text)
    if not m:
        return None
    out["count"] = int(m.group(1))
    ds = RE_DIA.findall(text)
    if not ds:
        return None
    out["dia"] = float(ds[0])
    if "完全贯穿" in text or "贯穿" in text:
        out["through"] = True
    else:
        out["through"] = False
    if "反面" in text or "背面" in text:
        out["face"] = "back"
    elif "正面" in text:
        out["face"] = "front"
    # 沉孔：⌴ 后面的第一个 φ 是沉口直径
    if CBORE in text:
        seg = text.split(CBORE, 1)[1]
        md = RE_DIA.search(seg)
        if md:
            out["cbore_dia"] = float(md.group(1))
        dd = re.search(r"▽\s*(\d+(?:\.\d+)?)", text)
        if dd:
            out["cbore_depth"] = float(dd.group(1))
    else:
        # 没有 ⌴ 但有 ▽ = 盲孔深度（例：4 × Ø5 H7 ▽10）
        if "▽" in text:
            dd = re.search(r"▽\s*(\d+(?:\.\d+)?)", text)
            if dd:
                out["depth"] = float(dd.group(1))
                out["through"] = False
    fit = re.search(r"\b(H\d+)\b", text)
    if fit:
        out["fit"] = fit.group(1)
    return out


def merge_fragments(frags):
    """把同一处图注的几段拼起来：同行右侧的「▽10」、下一行的「反面 ⌴φ11▽6.8」。"""
    used = set()
    holes, other, unparsed = [], [], []
    boxes = [frag_bbox(f) for f in frags]

    for i, fr in enumerate(frags):
        if i in used:
            continue
        txt = frag_text(fr)
        if not RE_COUNTED.search(txt):
            continue
        used.add(i)
        x0, x1, y = boxes[i]
        parts = [txt]

        # ① 同一行右侧、隔着一段水平距离的深度标注（▽10 常被公差框挤开）
        for j, fo in enumerate(frags):
            if j in used:
                continue
            ox0, ox1, oy = boxes[j]
            ot = frag_text(fo)
            if abs(oy - y) > 3.0 or not (x0 < ox0 <= x1 + 45.0):
                continue
            if not (ot.lstrip()[:1] in (DEPTH, CBORE) or re.match(r"^[▽⌴]", ot)):
                continue
            used.add(j)
            parts.append(ot)

        # ② 正下方、左端对齐的续行
        for j, fo in enumerate(frags):
            if j in used:
                continue
            ox0, ox1, oy = boxes[j]
            ot = frag_text(fo)
            if not (0 < (oy - y) <= 26.0):
                continue
            if not (CBORE in ot or "反面" in ot or "背面" in ot or re.search(r"▽\s*\d", ot)):
                continue
            if not (abs(ox0 - x0) <= 40 or x0 < ox0 < x1):
                continue
            used.add(j)
            parts.append(ot)
            break

        rec = parse_callout(" ".join(parts))
        if rec:
            holes.append(rec)
        else:
            unparsed.append(" ".join(parts))

    for i, fr in enumerate(frags):
        if i in used:
            continue
        txt = frag_text(fr)
        if RE_FILLET.search(txt):
            m = RE_FILLET.search(txt)
            other.append({"kind": "fillet", "count": int(m.group(1)), "r": float(m.group(2)),
                          "raw": txt})
        elif RE_SLOT.search(txt) and ("贯穿" in txt or "X" in txt or "x" in txt):
            m = RE_SLOT.search(txt)
            other.append({"kind": "slot", "a": float(m.group(1)), "b": float(m.group(2)),
                          "through": "贯穿" in txt, "raw": txt})
    return holes, other, unparsed


def main():
    if len(sys.argv) < 2:
        print("用法: drawing_spec.py 图纸.pdf [drawing_spec.json]")
        return 2
    pdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(pdf)), "drawing_spec.json")

    doc = pymupdf.open(pdf)
    holes, other, unparsed, nsym = [], [], [], 0
    for page in doc:
        toks, n = page_tokens(page)
        nsym += n
        frags = split_lines(toks)
        h, o, u = merge_fragments(frags)
        holes += h
        other += o
        unparsed += u

    print("符号识别 %d 个（φ/⌴/▽），解析出孔图注 %d 条" % (nsym, len(holes)))
    print("")
    print("%-6s %-8s %-8s %-6s %-10s %s" % ("数量", "孔径", "通/盲", "面", "沉孔", "原始判定"))
    total = 0
    for h in holes:
        total += h["count"]
        tb = "通孔" if h.get("through") else ("盲孔▽%g" % h["depth"] if h.get("depth") else "?")
        cb = ""
        if h.get("cbore_dia"):
            cb = "⌴φ%g▽%g" % (h["cbore_dia"], h.get("cbore_depth", 0))
        print("%-6d %-8s %-8s %-6s %-10s" % (
            h["count"], "φ%g" % h["dia"], tb, "反面" if h.get("face") == "back" else "正面", cb))

    spec = {
        "source": os.path.basename(pdf),
        "holes": holes,
        "other_callouts": other,
        "unparsed": unparsed,
        "total_holes": total,
        "symbols_found": nsym,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    print("")
    print("孔位合计 %d 个，写入 %s" % (total, out))
    if other:
        print("另有非孔图注 %d 条（槽等）: %s" % (len(other), "; ".join(o["raw"] for o in other)))
    if unparsed:
        print("")
        print("!! 有 %d 条图注没能解析，必须人工确认：" % len(unparsed))
        for u in unparsed:
            print("   ", u)
        return 1
    if not holes:
        print("!! 一条孔图注都没读出来：PDF 可能没有文字层（扫描件），需要 OCR")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
