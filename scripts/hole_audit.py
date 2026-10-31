# -*- coding: utf-8 -*-
"""孔系自检：把 DWG 解析出的圆 和 STEP 里的真实孔壁对起来，并报每个孔径的 z 起止。

用法（在图纸所在目录执行）：
    python hole_audit.py [零件.STEP] [part_segments.json]

判定规则（这几条都是踩过坑才加的）：
  1. DWG 里每个圆，STEP 里必须有对应孔位、对应直径
  2. 同心的 φ11/φ6.6 = 正面沉孔，φ11 段必须从某个端面起、深度等于图注
  3. segments json 里 back_counterbores 列的孔 = 反面沉孔，φ11 段必须从
     **另一端面** 起 —— 只看直径或只看体积都发现不了正反面对调
  4. 正面沉孔和反面沉孔不允许落在同一个面上（这就是"只做了一个面"的检查）
末行必须是 `问题 0 项`。
"""
import sys, os, json, glob, collections

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import step_geom

TOL = 0.15


def near(holes, x, y):
    return [h for h in holes if abs(h["x"] - x) < TOL and abs(h["y"] - y) < TOL]


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    seg = sys.argv[2] if len(sys.argv) > 2 else "part_segments.json"
    if not step or not os.path.exists(step):
        c = sorted(glob.glob("*.STEP") + glob.glob("*.step"))
        step = c[0] if c else step
    if not os.path.exists(step):
        raise SystemExit("找不到 STEP 文件，请把零件文件作为第一个参数传入")

    st = step_geom.Step(step)
    bb = st.bbox()
    zmin, zmax = round(bb[4], 3), round(bb[5], 3)
    depth = zmax - zmin
    # 孔壁：直径 ≤ 13、轴 ∥ z。R15/R80 那些是外形圆角，不是孔。
    holes = [h for h in st.holes() if 0.3 < h["r"] * 2 <= 13]

    print("文件: %s" % os.path.basename(step))
    print("包围盒 %.2f × %.2f × %.2f   原点 (%.2f, %.2f, %.2f)" % (
        bb[1] - bb[0], bb[3] - bb[2], depth, bb[0], bb[2], zmin))
    print("孔壁 %d 个，直径分组: %s" % (
        len(holes),
        dict(sorted(collections.Counter(round(h["r"] * 2, 2) for h in holes).items()))))

    circles = []
    spec = {}
    if seg and os.path.exists(seg):
        d = json.load(open(seg, encoding="utf-8"))
        circles = [(s["c"][0], s["c"][1], s["r"] * 2) for s in d["segments"] if s["t"] == "circle"]
        spec = d.get("back_counterbores") or {}
        print("DWG 圆 %d 个，直径分组: %s" % (
            len(circles),
            dict(sorted(collections.Counter(round(c[2], 2) for c in circles).items()))))
        if spec:
            print("图注反面沉孔: %d 处 ⌴φ%g ▽%g" % (
                len(spec["origins"]), spec["mouth_dia"], spec["depth"]))
    else:
        print("(未提供 DWG 分段，只做 STEP 自检)")

    back_origins = [tuple(o) for o in spec.get("origins", [])]
    back_mouth = float(spec.get("mouth_dia", 0) or 0)
    back_depth = float(spec.get("depth", 0) or 0)

    print("\n%-18s %-9s %-40s %s" % ("孔位(x, y)", "DWG", "STEP 实测 (直径 z起~z止)", "结论"))
    print("-" * 100)
    errs = []
    front_n = back_n = 0
    front_faces, back_faces = set(), set()

    def face_of(h, dia):
        if h["z0"] <= zmin + 0.02:
            return "下(z=%.1f)" % zmin
        if h["z1"] >= zmax - 0.02:
            return "上(z=%.1f)" % zmax
        return "中间"

    # DWG 里同心的 φ11 + φ6.6 是两行圆、一个孔位，按孔位合并再比。
    pos = collections.defaultdict(set)
    for x, y, dd in circles:
        pos[(round(x, 2), round(y, 2))].add(round(dd, 2))

    for (x, y), dias_dwg in sorted(pos.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        dd = min(dias_dwg)
        got = near(holes, x, y)
        ds = sorted(got, key=lambda h: -h["r"])
        desc = " + ".join("φ%g %.1f~%.1f" % (round(h["r"] * 2, 2), h["z0"], h["z1"]) for h in ds)
        dias = set(round(h["r"] * 2, 2) for h in got)

        if not got:
            verdict = "!! STEP 里没有这个孔"
            errs.append("(%.1f,%.1f) 缺孔" % (x, y))
        elif not dias_dwg.issubset(dias):
            verdict = "!! 直径不符"
            errs.append("(%.1f,%.1f) 要 φ%s，实际 %s" % (
                x, y, "/".join("%g" % v for v in sorted(dias_dwg)), sorted(dias)))
        else:
            is_back = any(abs(ox - x) < 0.05 and abs(oy - y) < 0.05 for ox, oy in back_origins)
            big = max(got, key=lambda h: h["r"]) if got else None
            has_step = len(dias) >= 2

            if is_back:
                back_n += 1
                if not has_step or abs(big["r"] * 2 - back_mouth) > 0.05:
                    verdict = "!! 反面沉孔没做出来"
                    errs.append("(%.1f,%.1f) 要反面 ⌴φ%g ▽%g，实际 %s" % (x, y, back_mouth, back_depth, desc))
                elif abs(big["z1"] - zmax) > 0.02 or abs(big["z0"] - (zmax - back_depth)) > 0.05:
                    verdict = "!! 反面沉孔位置/深度不对"
                    errs.append("(%.1f,%.1f) φ%g 应在 %.1f~%.1f，实际 %.1f~%.1f" % (
                        x, y, back_mouth, zmax - back_depth, zmax, big["z0"], big["z1"]))
                else:
                    verdict = "反面沉孔 OK ▽%g" % back_depth
                    back_faces.add(face_of(big, back_mouth))
            elif has_step:
                front_n += 1
                if abs(big["z0"] - zmin) > 0.02 and abs(big["z1"] - zmax) > 0.02:
                    verdict = "!! 沉孔悬在板中间"
                    errs.append("(%.1f,%.1f) 沉口没落在端面上" % (x, y))
                else:
                    verdict = "正面沉孔 OK ▽%g" % (big["z1"] - big["z0"])
                    front_faces.add(face_of(big, None))
            else:
                verdict = "单径孔 OK（通/盲见图注）"

        print("%-18s %-9s %-40s %s" % ("(%.1f, %.1f)" % (x, y),
                                       "/".join("φ%g" % v for v in sorted(dias_dwg)), desc, verdict))

    if front_faces and back_faces and front_faces & back_faces:
        errs.append("正反面沉孔落在同一个面 %s —— 只做了一个面" % sorted(front_faces))
        print("\n!! 正面沉孔在 %s，反面沉孔也在 %s" % (sorted(front_faces), sorted(back_faces)))

    print("\n正面沉孔 %d 处 %s   反面沉孔 %d 处 %s" % (
        front_n, sorted(front_faces) or "-", back_n, sorted(back_faces) or "-"))
    print("[汇总] 问题 %d 项" % len(errs))
    for e in errs[:20]:
        print("   " + e)
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
