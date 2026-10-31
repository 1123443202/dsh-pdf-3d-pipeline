# -*- coding: utf-8 -*-
"""验收器自测：把图注故意改错几处，spec_verify 必须都报错。

一个"永远返回 0 问题"的检查器，比没有检查器更危险——它会给人虚假的安全感。
所以这里做变异测试：拿一份已知正确的模型，把图注改坏，验证每一类错误都能被抓到。

用法：
    python diagnostics/gate_selftest.py drawing_spec.json 已知正确的.STEP

五项，全绿才算这道门是"活"的：
    原样                  必须 0 问题
    盲孔 ▽10 → ▽12        必须报错（小孔深一点，体积只差几十 mm³）
    沉孔 反面 → 正面       必须报错（体积一模一样）
    某条数量 +1            必须报错（少做几个孔）
    通孔改成盲孔           必须报错（打穿了）
"""
import sys
import os
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import json
import spec_verify


def run(spec, step):
    return spec_verify.check(spec, step, verbose=False)


def main():
    if len(sys.argv) < 3:
        print("用法: gate_selftest.py drawing_spec.json 已知正确的.STEP")
        return 2
    base = json.load(open(sys.argv[1], encoding="utf-8"))
    step = sys.argv[2]

    defects = []

    def case(name, mutate, want_zero):
        spec = copy.deepcopy(base)
        mutate(spec)
        n = run(spec, step)
        ok = (n == 0) if want_zero else (n > 0)
        print("  %-26s -> 问题 %-3d %s" % (name, n, "OK" if ok else "!! 没抓到"))
        if not ok:
            defects.append(name)

    def find(spec, pred):
        for h in spec["holes"]:
            if pred(h):
                return h
        return None

    case("原样（应通过）", lambda s: None, True)

    def deeper(s):
        h = find(s, lambda x: x.get("depth") and not x.get("cbore_dia"))
        if h is None:
            raise SystemExit("这份图注里没有盲孔，无法做深度变异")
        h["depth"] += 2.0
    case("盲孔深度 +2", deeper, False)

    def flip(s):
        h = find(s, lambda x: x.get("cbore_dia"))
        if h is None:
            raise SystemExit("这份图注里没有沉孔，无法做翻面变异")
        h["face"] = "front" if h.get("face") == "back" else "back"
    case("沉孔翻到另一面", flip, False)

    def count(s):
        s["holes"][0]["count"] += 1
    case("某条数量 +1", count, False)

    def blind(s):
        # 优先挑一个"纯通孔"；没有就把某个带沉孔的通孔改成普通盲孔
        h = find(s, lambda x: x.get("through") and not x.get("cbore_dia"))
        if h is None:
            h = find(s, lambda x: x.get("through"))
        if h is None:
            raise SystemExit("这份图注里没有通孔，无法做盲孔变异")
        h["through"] = False
        h["depth"] = 10.0
        h.pop("cbore_dia", None)
        h.pop("cbore_depth", None)
    case("通孔改成盲孔 ▽10", blind, False)

    print("")
    if defects:
        print("[FAIL] 这些变异没被抓住：%s" % ", ".join(defects))
        return 1
    print("[PASS] 验收器是活的：正确模型通过，5 类变异全部报错")
    return 0


if __name__ == "__main__":
    sys.exit(main())
