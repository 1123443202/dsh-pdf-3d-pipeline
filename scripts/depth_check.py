# -*- coding: utf-8 -*-
"""看一眼每个孔在 z 方向怎么分段：沉孔的 φ11 从哪个端面起、φ6.6 接到哪里。

    python depth_check.py 零件.STEP

只有把"起止"打出来，才能证明沉孔是正反两面都做了、而不是同一面做两遍。
"""
import sys, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import step_geom

path = sys.argv[1] if len(sys.argv) > 1 else ""
if not os.path.exists(path):
    import glob
    c = sorted(glob.glob("*.STEP") + glob.glob("*.step"))
    if not c:
        raise SystemExit("找不到 STEP 文件")
    path = c[0]

st = step_geom.Step(path)
bb = st.bbox()
zmin, zmax = round(bb[4], 3), round(bb[5], 3)
holes = [h for h in st.holes() if 0.3 < h["r"] * 2 <= 13]

print("%s   板厚 %.2f (z %.1f~%.1f)" % (os.path.basename(path), zmax - zmin, zmin, zmax))

groups = collections.defaultdict(list)
for h in holes:
    groups[(round(h["x"], 2), round(h["y"], 2))].append(h)

print("\n按 z 分段归类的孔（孔数 / 直径 / z起~z止）:")
key = collections.Counter()
for (x, y), v in groups.items():
    key[tuple(sorted((round(h["r"] * 2, 2), h["z0"], h["z1"]) for h in v))] += 1
for k, n in sorted(key.items(), key=lambda kv: (-kv[1], kv[0])):
    print("  %2d 处   %s" % (n, "   +   ".join("φ%g %.1f~%.1f" % t for t in k)))

print("\n沉孔明细:")
bad = 0
for (x, y), v in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    big = [h for h in v if h["r"] * 2 >= 10]
    if not big:
        continue
    b = max(big, key=lambda h: h["r"])
    side = "正面(z=%.0f)" % zmin if b["z0"] <= zmin + 0.02 else \
           ("反面(z=%.0f)" % zmax if b["z1"] >= zmax - 0.02 else "中间!!")
    if side == "中间!!":
        bad += 1
    print("  (%7.2f,%7.2f)  " % (x, y) + "  ".join(
        "φ%g@%.1f~%.1f" % (round(h["r"] * 2, 2), h["z0"], h["z1"]) for h in sorted(v, key=lambda h: -h["r"]))
        + "   " + side + " ▽%.1f" % (b["z1"] - b["z0"]))

# 退出码给上游闸门用：0 = 每个沉口都贴着某个端面，1 = 有沉口悬在板中间
sys.exit(0 if bad == 0 else 1)
