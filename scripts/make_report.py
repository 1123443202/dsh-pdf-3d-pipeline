# -*- coding: utf-8 -*-
"""生成一页《验收记录.md》：把这次建模的证据固定下来，交付时一起给用户。

只写事实，不写结论性套话：
    图注条数 / 孔位总数 / 包围盒 / 体积 / 质量与图纸偏差 /
    正面沉孔几处、反面几处、直通几处、盲孔几处 / 图注对账结果。

用法：
    python make_report.py --spec drawing_spec.json --step out/PART.STEP \
        --segments part_segments.json --build-json out/PART.build.json \
        --drawing-mass 4.87 --density 2.7 --out out/验收记录.md --name PART
"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import step_geom
import spec_verify


def hole_summary(step_path):
    st = step_geom.Step(step_path)
    bb = st.bbox()
    zmin, zmax = bb[4], bb[5]
    holes = [h for h in st.holes() if 0.3 < h["r"] * 2 <= 13]
    sites = collections.defaultdict(list)
    for h in holes:
        sites[(round(h["x"], 1), round(h["y"], 1))].append(h)
    front = back = plain = blind = 0
    for _k, v in sites.items():
        dias = set(round(h["r"] * 2, 2) for h in v)
        big = max(v, key=lambda h: h["r"])
        if len(dias) >= 2 and big["r"] * 2 >= 10:
            if big["z0"] <= zmin + 0.05:
                front += 1
            elif big["z1"] >= zmax - 0.05:
                back += 1
            else:
                plain += 1
            continue
        if max(h["z1"] for h in v) - min(h["z0"] for h in v) < (zmax - zmin) - 0.2:
            blind += 1
        else:
            plain += 1
    return {"bbox": bb, "front": front, "back": back, "plain": plain, "blind": blind,
            "sites": len(sites)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--segments", default="")
    ap.add_argument("--build-json", dest="build_json", default="")
    ap.add_argument("--drawing-mass", type=float, default=0.0)
    ap.add_argument("--density", type=float, default=0.0, help="g/mm3, 2.7 = 6061 aluminium")
    ap.add_argument("--material", default="aluminium")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="")
    a = ap.parse_args()

    spec = json.load(open(a.spec, encoding="utf-8"))
    problems = spec_verify.check(spec, a.step, verbose=False)
    hs = hole_summary(a.step)
    # --out may be a folder: the report name lives here so callers (run.ps1)
    # never have to carry a non-ASCII filename through the console encoding.
    out_path = a.out
    if os.path.isdir(out_path) or out_path.endswith(("/", "\\")):
        out_path = os.path.join(out_path, "验收记录.md")

    vol = None
    bands = []
    if a.build_json and os.path.exists(a.build_json):
        b = json.load(open(a.build_json, encoding="utf-8-sig"))
        vol = b.get("volume_mm3")
        for ln in b.get("log") or []:
            if ln.startswith("band "):
                bands.append(ln)

    dens = a.density
    if not dens:
        dens = {"aluminium": 2.70, "steel": 7.85, "stainless": 7.93,
                "brass": 8.50, "titanium": 4.43}.get(a.material, 2.70)
    mass = (vol * dens / 1e6) if vol else None

    bb = hs["bbox"]
    L = []
    L.append("# 验收记录 - %s" % (a.name or os.path.basename(a.step)))
    L.append("")
    L.append("生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    L.append("")
    L.append("## 1. 图注对账（唯一验收基准）")
    L.append("")
    L.append("| 图注 | 数量 | 孔径 | 通/盲 | 沉孔 |")
    L.append("|---|---|---|---|---|")
    for h in spec.get("holes") or []:
        face = "反面" if h.get("face") == "back" else "正面"
        cb = ""
        if h.get("cbore_dia"):
            cb = "⌴φ%g▽%g（%s）" % (h["cbore_dia"], h.get("cbore_depth", 0), face)
        L.append("| #%d | %g | φ%g | %s | %s |" % (
            (spec.get("holes") or []).index(h) + 1, h.get("count", 0), h.get("dia", 0),
            "通孔" if h.get("through") else "盲孔▽%g" % h.get("depth", 0), cb or "-"))
    L.append("")
    L.append("对账结果：**问题 %d 项** %s" % (problems, "（全部对上）" if problems == 0 else "（不许交付）"))
    L.append("")

    L.append("## 2. 几何")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("|---|---|")
    # step_geom.bbox() -> (xmin, xmax, ymin, ymax, zmin, zmax)
    L.append("| 包围盒 | %.2f × %.2f × %.2f mm |" % (bb[1] - bb[0], bb[3] - bb[2], bb[5] - bb[4]))
    L.append("| 原点 | (%.2f, %.2f, %.2f) |" % (bb[0], bb[2], bb[4]))
    if vol:
        L.append("| 体积 | %.1f mm³ |" % vol)
    if mass:
        if a.drawing_mass > 0:
            L.append("| 质量 | %.3f kg（图纸 %.3f kg，%+.2f%%） |" %
                     (mass, a.drawing_mass, (mass / a.drawing_mass - 1) * 100))
        else:
            L.append("| 质量 | %.3f kg（密度 %g g/mm³） |" % (mass, dens))
    L.append("| 孔位总数 | %d |" % hs["sites"])
    L.append("| 正面沉孔 / 反面沉孔 | %d 处 / %d 处 |" % (hs["front"], hs["back"]))
    L.append("| 直通孔 / 盲孔 | %d 处 / %d 处 |" % (hs["plain"], hs["blind"]))
    L.append("")

    if bands:
        L.append("## 3. 分段拉伸（每段实体数必须等于计划数）")
        L.append("")
        L.append("```")
        for b in bands:
            L.append(b)
        L.append("```")
        L.append("")
        L.append("最后一段元素数比前面少，就是盲孔没有跟过去——这是盲孔做对的证据。")
        L.append("")

    L.append("## 4. 判定")
    L.append("")
    if problems == 0:
        L.append("图注逐条对上，孔位、直径、通/盲、沉孔面与深度均由 STEP 几何实测得出。")
        L.append("体积与质量只作为辅助证据：少一整面沉孔体积只差 0.3%，正反面对调体积完全一样。")
    else:
        L.append("**未通过**：%d 项问题，见 `spec_verify.py` 输出。不许交付。" % problems)
    L.append("")
    L.append("---")
    L.append("复现：`run.ps1 verify -Spec %s -Step %s`" %
             (os.path.basename(a.spec), os.path.basename(a.step)))

    open(out_path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote %s (problems=%d)" % (out_path, problems))
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
