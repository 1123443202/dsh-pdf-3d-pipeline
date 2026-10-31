# -*- coding: utf-8 -*-
"""拿图纸图注（drawing_spec.json）去验收 STEP 几何，逐条对账。

为什么要对「图注」而不是对「DWG 圆」：
    DWG 只画了它画了的东西。本零件 16 个孔的 ⌴φ11▽6.8 只写在图注里，
    4 个 φ5 的「▽10」也只写在图注里（画出来和通孔一模一样）。
    拿 DWG 的圆去验收，永远得到"孔全对"的结论——因为基准本身就是错的。
    这里把图注当合同：数量、孔径、通/盲、沉孔直径与深度、沉孔在哪一面，
    逐条落到几何上，对不上就报。

判定依据是每个孔壁圆柱面的直径 + z 起止，不看体积。
少一整面沉孔体积只差 0.3%；正反面对调体积完全一样；盲孔打穿只差 0.02%。

用法：
    python spec_verify.py drawing_spec.json 零件.STEP      # 退出码 0 = 全过
    也可 import check(spec, step_path)，供 diagnostics/gate_selftest.py 自测
"""
import sys
import os
import json
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import step_geom

DTOL = 0.08        # 直径容差 mm
ZTOL = 0.25        # z 容差 mm
EDGE = 0.8         # 圆心离包围盒边界小于这个值，算外形圆角，不当孔


def load_sites(step):
    """把圆柱面按同心位置合成「孔位」，每个孔位带若干层（直径 + z 起止）。"""
    holes = step.holes()
    bbox = step.bbox()
    x0, x1, y0, y1, z0, z1 = bbox
    sites, skipped = {}, collections.Counter()
    for h in holes:
        dia = round(h["r"] * 2.0, 3)
        near_edge = (abs(h["x"] - x0) < EDGE or abs(h["x"] - x1) < EDGE
                     or abs(h["y"] - y0) < EDGE or abs(h["y"] - y1) < EDGE)
        if near_edge:
            skipped["外形圆角 φ%g" % dia] += 1
            continue
        key = (round(h["x"], 2), round(h["y"], 2))
        sites.setdefault(key, []).append({"dia": dia, "z0": h["z0"], "z1": h["z1"]})
    for k in sites:
        sites[k].sort(key=lambda l: (l["z0"], -l["dia"]))
    return sites, (z0, z1), skipped


def expected_layers(hole, thick):
    """图注 -> 该孔位应有的层 [(dia, z0, z1)]。"""
    d = hole["dia"]
    layers = []
    if hole.get("cbore_dia"):
        cb_d = hole["cbore_dia"]
        cb_t = hole.get("cbore_depth", 0.0)
        if hole.get("face") == "back":
            layers.append((d, 0.0, thick - cb_t))
            layers.append((cb_d, thick - cb_t, thick))
        else:
            layers.append((cb_d, 0.0, cb_t))
            layers.append((d, cb_t, thick))
    elif hole.get("depth") and not hole.get("through"):
        if hole.get("face") == "back":
            layers.append((d, thick - hole["depth"], thick))
        else:
            layers.append((d, 0.0, hole["depth"]))
    else:
        layers.append((d, 0.0, thick))
    return layers


def same(layers, expect):
    if len(layers) != len(expect):
        return False
    used = [False] * len(layers)
    for (d, a, b) in expect:
        hit = False
        for i, l in enumerate(layers):
            if used[i]:
                continue
            if abs(l["dia"] - d) <= DTOL and abs(l["z0"] - a) <= ZTOL and abs(l["z1"] - b) <= ZTOL:
                used[i] = True
                hit = True
                break
        if not hit:
            return False
    return True


def desc(layers):
    return " + ".join("φ%g %.1f~%.1f" % (l["dia"], l["z0"], l["z1"]) for l in layers)


def label_of(h):
    s = "%d × φ%g %s" % (h["count"], h["dia"], "通孔" if h.get("through") else "盲孔")
    if h.get("cbore_dia"):
        s += " %s⌴φ%g▽%g" % ("反面" if h.get("face") == "back" else "正面",
                             h["cbore_dia"], h.get("cbore_depth", 0))
    elif h.get("depth"):
        s += "▽%g" % h["depth"]
    return s


def check(spec, step_path, verbose=True):
    """返回问题数。verbose=True 时把逐条对账打印出来。"""
    step = step_geom.Step(step_path)
    sites, (z0, z1), skipped = load_sites(step)
    thick = round(z1 - z0, 3)

    slots = [o for o in spec.get("other_callouts", []) if o.get("kind") == "slot"]
    slot_dias = set(round(min(o["a"], o["b"]), 2) for o in slots)
    # 图纸上标了 12×R20 / 8×R3 这类过渡圆角，它们的圆柱面不该被当成孔
    fillets = [o for o in spec.get("other_callouts", []) if o.get("kind") == "fillet"]
    fillet_dias = set(round(2.0 * o["r"], 2) for o in fillets)

    if verbose:
        print("图注: %s   模型: %s   板厚 %.2f"
              % (spec.get("source"), os.path.basename(step_path), thick))
        print("")
        print("%-34s %-6s %-6s %-6s %s" % ("图注", "要求", "实得", "判定", "说明"))

    problems = 0
    used = set()
    near_miss, near_keys = [], set()

    for h in spec["holes"]:
        exp = expected_layers(h, thick)
        got = 0
        for k, layers in sites.items():
            if k in used:
                continue
            if same(layers, exp):
                used.add(k)
                got += 1
        ok = got == h["count"]
        if not ok:
            problems += 1
            for k, layers in sites.items():
                if k in used or k in near_keys:
                    continue
                if any(abs(l["dia"] - h["dia"]) <= DTOL for l in layers):
                    near_miss.append((k, layers, exp))
                    near_keys.add(k)
        if verbose:
            print("%-34s %-6d %-6d %-6s" % (label_of(h), h["count"], got, "OK" if ok else "FAIL"))

    if verbose:
        for k, layers, exp in near_miss[:8]:
            print("    实际 (%.1f, %.1f): %s   期望: %s"
                  % (k[0], k[1], desc(layers), " + ".join("φ%g %.1f~%.1f" % e for e in exp)))

    real_left = []
    for k, layers in sites.items():
        if k in used:
            continue
        dias = set(round(l["dia"], 2) for l in layers)
        if dias and any(abs(d - v) <= DTOL for d in dias for v in slot_dias):
            continue                                  # 腰形槽端头，图注里是槽不是孔
        if dias and any(abs(d - v) <= DTOL for d in dias for v in fillet_dias):
            continue                                  # 图纸标了的过渡圆角
        if k in near_keys:
            continue                                  # 上面已作为"像但不符"报过
        real_left.append((k, layers))
    if real_left:
        problems += len(real_left)
        if verbose:
            print("")
            print("图中没有、模型里有的孔 %d 个：" % len(real_left))
            for k, layers in sorted(real_left)[:10]:
                print("    (%.1f, %.1f) %s" % (k[0], k[1], desc(layers)))

    if verbose and skipped:
        print("")
        print("未计入孔的圆柱面（外形圆角/槽端）: %s"
              % ", ".join("%s×%d" % (k, v) for k, v in sorted(skipped.items())))

    if verbose:
        print("")
        if problems == 0:
            print("[汇总] 图注 %d 条全部对上，问题 0 项" % len(spec["holes"]))
        else:
            print("[汇总] 问题 %d 项 —— 模型与图注不符，不许交付" % problems)
    return problems


def main():
    if len(sys.argv) < 3:
        print("用法: spec_verify.py drawing_spec.json 零件.STEP")
        return 2
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    problems = check(spec, sys.argv[2], verbose=True)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
