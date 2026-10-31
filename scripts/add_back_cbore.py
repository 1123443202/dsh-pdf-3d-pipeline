# -*- coding: utf-8 -*-
"""把"只写在图注里、DWG 里没有第二个圆"的沉孔记进 part_segments.json。

典型图纸标注：

    16 × φ6.6 完全贯穿
    反面 ⌴φ11 ▽6.8

DWG 里只有 16 个 φ6.6 的圆，φ11 只存在于文字里，几何解析永远看不到它，
于是模型上就只有一个面的沉孔。这个脚本把那条图注翻译成：

    "back_counterbores": {"mouth_dia": 11.0, "depth": 6.8, "origins": [[x,y], ...]}

DwgBuild.cs 读到这个字段后，就会在反面（z = 板厚）补出 φ11 沉口。

用法：
    python add_back_cbore.py part_segments.json --bore-dia 6.6 --mouth-dia 11 --depth 6.8
    python add_back_cbore.py part_segments.json --bore-dia 6.6 --mouth-dia 11 --depth 6.8 \
        --origins 30,113.5 110,113.5          # 只给指定的几个孔

--origins 省略时，自动选中所有"没有同心圆、直径等于 --bore-dia"的孔
（即纯通孔；已经带正面沉孔的那个小圆不会被选中）。
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("segments")
    ap.add_argument("--bore-dia", type=float, required=True, help="沉孔所在的通孔直径，如 6.6")
    ap.add_argument("--mouth-dia", type=float, required=True, help="沉孔大径，如 11")
    ap.add_argument("--depth", type=float, required=True, help="沉孔深度，如 6.8")
    ap.add_argument("--origins", nargs="*", default=None, help="x,y 形式的孔心，省略则自动挑")
    ap.add_argument("--clear", action="store_true", help="先清掉已有的 back_counterbores")
    a = ap.parse_args()

    d = json.load(open(a.segments, encoding="utf-8"))
    segs = d["segments"]
    cir = [s for s in segs if s["t"] == "circle"]

    def has_concentric(s):
        for o in cir:
            if o is s:
                continue
            if abs(o["c"][0] - s["c"][0]) < 0.01 and abs(o["c"][1] - s["c"][1]) < 0.01:
                return True
        return False

    if a.origins:
        want = []
        for t in a.origins:
            x, y = [float(v) for v in t.split(",")]
            hit = [s for s in cir
                   if abs(s["c"][0] - x) < 0.05 and abs(s["c"][1] - y) < 0.05
                   and abs(s["r"] * 2 - a.bore_dia) < 0.1]
            if not hit:
                sys.exit("在 (%.2f, %.2f) 找不到 φ%g 的孔" % (x, y, a.bore_dia))
            want.append(hit[0])
    else:
        want = [s for s in cir
                if abs(s["r"] * 2 - a.bore_dia) < 0.1 and not has_concentric(s)]

    if not want:
        sys.exit("没有找到符合 φ%g 的纯通孔，请检查 --bore-dia" % a.bore_dia)

    if a.clear or True:
        d["back_counterbores"] = {
            "mouth_dia": a.mouth_dia,
            "depth": a.depth,
            "origins": [[round(s["c"][0], 4), round(s["c"][1], 4)] for s in want],
        }
    json.dump(d, open(a.segments, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("写入 back_counterbores: %d 个孔, 反面 ⌴φ%g ▽%g" % (len(want), a.mouth_dia, a.depth))
    for s in sorted(want, key=lambda s: (s["c"][1], s["c"][0])):
        print("   (%8.2f, %8.2f)" % (s["c"][0], s["c"][1]))


if __name__ == "__main__":
    main()
