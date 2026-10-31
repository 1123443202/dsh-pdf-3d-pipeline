# -*- coding: utf-8 -*-
"""从 SolidWorks 导出的 STEP 里量孔：位置、直径、以及每个孔径沿 z 的起止。

只认板厚方向（轴 ∥ z）的圆柱面，所以量到的都是孔壁，不会把外圆角混进来。

为什么要量 z 起止：沉孔做没做出台阶，光看体积看不出来（少 8 个沉孔只差 0.02%），
光看直径也看不出来（正反面对调，直径一样、体积一样）。只有起止对上了，
才能说"φ11 在 0~6.8、φ6.6 在 6.8~15"这种话。
"""
import re

__all__ = ["Step"]


class Step(object):
    def __init__(self, path):
        txt = open(path, "r", encoding="utf-8", errors="ignore").read()
        ents, cur, buf = {}, None, []
        for ln in txt.splitlines():
            if ln.startswith("#"):
                if cur is not None:
                    ents[cur] = " ".join(buf)
                m = re.match(r"#(\d+)\s*=\s*", ln)
                cur = int(m.group(1)) if m else None
                buf = [ln[m.end():] if m else ln]
            elif cur is not None:
                buf.append(ln.strip())
        if cur is not None:
            ents[cur] = " ".join(buf)
        self.ents = ents

    # ---------- 低层 ----------
    def typ(self, eid):
        m = re.match(r"([A-Z_0-9]+)", self.ents.get(eid, ""))
        return m.group(1) if m else ""

    def refs(self, eid):
        return [int(x) for x in re.findall(r"#(\d+)", self.ents.get(eid, ""))]

    def nums(self, eid):
        s = self.ents.get(eid, "")
        body = s[s.find("(") + 1:] if "(" in s else s
        body = re.sub(r"#[0-9]+", " ", body)
        return [float(x) for x in re.findall(r"-?\d+\.?\d*(?:[Ee][-+]?\d+)?", body)]

    def point(self, eid):
        t = self.typ(eid)
        if t == "VERTEX_POINT":
            r = self.refs(eid)
            return self.point(r[0]) if r else None
        if t == "CARTESIAN_POINT":
            v = self.nums(eid)[:3]
            while len(v) < 3:
                v.append(0.0)
            return tuple(v)
        return None

    def axis(self, eid):
        if self.typ(eid) != "AXIS2_PLACEMENT_3D":
            return None, None
        r = self.refs(eid)
        o = self.point(r[0]) if r else None
        d = (0.0, 0.0, 1.0)
        if len(r) > 1 and self.typ(r[1]) == "DIRECTION":
            v = self.nums(r[1])[:3]
            while len(v) < 3:
                v.append(0.0)
            d = tuple(v)
        return o, d

    # ---------- 面 ----------
    def _face_edges(self, face):
        """面的所有边（ORIENTED_EDGE -> EDGE_CURVE）引用。"""
        out = []
        for b in self.refs(face):
            if not self.typ(b).endswith("_BOUND"):
                continue
            for loop in self.refs(b):
                if self.typ(loop) != "EDGE_LOOP":
                    continue
                for oe in self.refs(loop):
                    if self.typ(oe) != "ORIENTED_EDGE":
                        continue
                    r = self.refs(oe)
                    if r and self.typ(r[0]) == "EDGE_CURVE":
                        out.append(r[0])
        return out

    def _edge_circle_z(self, ec):
        """边若是圆，返回圆心 z；否则 None。"""
        r = self.refs(ec)
        if len(r) < 3:
            return None
        curve = r[2]
        if self.typ(curve) != "CIRCLE":
            return None
        cr = self.refs(curve)
        if not cr:
            return None
        o, _ = self.axis(cr[0])
        return o[2] if o else None

    def _face_cyl(self, face):
        """面若是圆柱面，返回 (radius, cx, cy, dir_z)。"""
        r = self.refs(face)
        if not r:
            return None
        surf = r[-1]
        if self.typ(surf) != "CYLINDRICAL_SURFACE":
            return None
        sr = self.refs(surf)
        n = self.nums(surf)
        if not sr or not n:
            return None
        o, d = self.axis(sr[0])
        if o is None:
            return None
        return (n[-1], o[0], o[1], d[2], o[2])

    # ---------- 孔 ----------
    def holes(self):
        """[{r, x, y, z0, z1}]，只含轴平行于 z 的圆柱面。"""
        out = []
        for face in list(self.ents):
            if self.typ(face) != "ADVANCED_FACE":
                continue
            cyl = self._face_cyl(face)
            if cyl is None:
                continue
            r, cx, cy, dz, oz = cyl
            if abs(abs(dz) - 1.0) > 1e-3:
                continue
            zs = []
            for ec in self._face_edges(face):
                z = self._edge_circle_z(ec)
                if z is not None:
                    zs.append(z)
            if len(zs) >= 2:
                z0, z1 = min(zs), max(zs)
            else:
                z0 = z1 = oz          # 量不到边界时退回轴线原点，宁可保守也不编
            out.append({"r": r, "x": cx, "y": cy, "z0": round(z0, 3), "z1": round(z1, 3)})
        # SolidWorks writes a cylinder as two half faces along the seam, so the
        # same hole shows up twice; collapse it.
        seen, uniq = set(), []
        for h in out:
            k = (round(h["x"], 2), round(h["y"], 2), round(h["r"], 3), h["z0"], h["z1"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(h)
        uniq.sort(key=lambda h: (round(h["y"], 2), round(h["x"], 2), -h["r"]))
        return uniq

    def bbox(self):
        xs, ys, zs = [], [], []
        for eid in self.ents:
            if self.typ(eid) == "CARTESIAN_POINT":
                v = self.nums(eid)[:3]
                while len(v) < 3:
                    v.append(0.0)
                xs.append(v[0]); ys.append(v[1]); zs.append(v[2])
        if not xs:
            return None
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
