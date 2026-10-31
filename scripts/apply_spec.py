# -*- coding: utf-8 -*-
"""把图注里"几何表达不出来"的信息补进 part_segments.json。

有两类东西 DWG 画不出来，只能靠图注：
  1. 只写了"反面 ⌴φ11▽6.8"、但只画了一圈 φ6.6 的沉孔  -> back_counterbores
  2. "4 × φ5 H7 ▽10" 这种盲孔，图上和通孔长得一模一样  -> blind_holes

本脚本按 drawing_spec.json 的数量去匹配几何里的圆，数量对不上就报错退出，
不猜、不强行套——宁可停下，也不要建出一个"看着对"的零件。

用法：
    python apply_spec.py part_segments.json drawing_spec.json
"""
import sys
import os
import json
import copy


def dia(s):
    return round(2.0 * float(s["r"]), 3)


def has_partner(circles, c, bigger):
    for o in circles:
        if o is c:
            continue
        if abs(o["c"][0] - c["c"][0]) > 0.01 or abs(o["c"][1] - c["c"][1]) > 0.01:
            continue
        d, od = dia(c), dia(o)
        if bigger and od > d + 0.02:
            return True
        if not bigger and od < d - 0.02:
            return True
    return False


def main():
    if len(sys.argv) < 3:
        print("用法: apply_spec.py part_segments.json drawing_spec.json")
        return 2
    seg_path, spec_path = sys.argv[1], sys.argv[2]
    data = json.load(open(seg_path, encoding="utf-8"))
    spec = json.load(open(spec_path, encoding="utf-8"))
    circles = [s for s in data["segments"] if s.get("t") == "circle"]

    problems = []
    used = set()
    back = None
    blind = None

    # 先处理正面沉孔：它是 DWG 里成对画出来的，只做数量核对
    for h in spec["holes"]:
        if not h.get("cbore_dia") or h.get("face") == "back":
            continue
        pairs = [c for c in circles
                 if abs(dia(c) - h["dia"]) <= 0.08 and has_partner(circles, c, True)]
        if len(pairs) != h["count"]:
            problems.append("正面沉孔 φ%g：图注 %d 处，DWG 里成对画的 %d 处"
                            % (h["dia"], h["count"], len(pairs)))

    # 反面沉孔：几何里根本没有第二圈，按原点写进去
    for h in spec["holes"]:
        if not h.get("cbore_dia") or h.get("face") != "back":
            continue
        cand = [c for c in circles
                if abs(dia(c) - h["dia"]) <= 0.08
                and not has_partner(circles, c, True) and not has_partner(circles, c, False)
                and id(c) not in used]
        if len(cand) != h["count"]:
            problems.append("反面沉孔 φ%g：图注 %d 处，可用的光孔 %d 个"
                            % (h["dia"], h["count"], len(cand)))
            continue
        back = {"mouth_dia": h["cbore_dia"], "depth": h["cbore_depth"],
                "origins": [[round(c["c"][0], 3), round(c["c"][1], 3)] for c in cand]}
        for c in cand:
            used.add(id(c))
        print("反面沉孔：%d 处 φ%g，沉口 φ%g▽%g" % (len(cand), h["dia"], h["cbore_dia"], h["cbore_depth"]))

    # 盲孔：图上就是个圆，只有图注知道它多深
    for h in spec["holes"]:
        if h.get("through") or h.get("cbore_dia") or not h.get("depth"):
            continue
        cand = [c for c in circles
                if abs(dia(c) - h["dia"]) <= 0.08
                and not has_partner(circles, c, True) and not has_partner(circles, c, False)
                and id(c) not in used]
        if len(cand) != h["count"]:
            problems.append("盲孔 φ%g▽%g：图注 %d 处，可用的光孔 %d 个"
                            % (h["dia"], h["depth"], h["count"], len(cand)))
            continue
        blind = {"dia": h["dia"], "depth": h["depth"],
                 "origins": [[round(c["c"][0], 3), round(c["c"][1], 3)] for c in cand]}
        for c in cand:
            used.add(id(c))
        print("盲孔：%d 处 φ%g 深 %g" % (len(cand), h["dia"], h["depth"]))

    if problems:
        print("")
        print("!! 图注与几何数量对不上，不能继续：")
        for p in problems:
            print("   ", p)
        return 1

    out = copy.deepcopy(data)
    out.pop("back_counterbores", None)
    out.pop("blind_holes", None)
    if back:
        out["back_counterbores"] = back
    if blind:
        out["blind_holes"] = blind
    json.dump(out, open(seg_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("")
    print("已写回 %s" % seg_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
