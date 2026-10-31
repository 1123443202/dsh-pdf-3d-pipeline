using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

/// <summary>
/// Build a part from geometry that came out of a DWG/DXF.
///
/// Two things were learned the hard way on this machine and are encoded here:
///
/// 1. The SolidWorks DXF importer produces a sketch this API cannot base-
///    extrude (41 closed contours, every selection/parameter combination
///    fails, while the same call on a hand-drawn sketch succeeds). The
///    segments are replayed instead — the geometry still comes from the DWG.
///
/// 2. A counterbore drawn as a second, concentric circle in the same sketch
///    breaks the base extrude outright (bisected: fine at 28 holes, dead at
///    32 once the concentric pairs appear). Pockets are therefore built as a
///    second, offset layer instead of a concentric circle or an offset cut.
/// </summary>
public static class DwgBuild
{
    static ISldWorks sw;
    static IModelDoc2 md;

    public static string Build(string segPath, string outDir, string name, double counterboreDepth)
    {
        var log = new List<string>();
        var res = new Dictionary<string, object>();
        res["ok"] = false;
        res["log"] = log;
        res["files"] = new List<string>();
        try
        {
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
                File.ReadAllText(segPath, Encoding.UTF8));
            double depth = Convert.ToDouble(data["depth_mm"]);
            var segs = (IList)data["segments"];

            // A counterbore is a small circle sitting on the same centre as a
            // bigger one. The BIG circle is the pocket; the small one stays a
            // plain through hole. They MUST go on different layers -- SolidWorks
            // silently drops a concentric pair of different radii inside a
            // single sketch, which is exactly how an earlier build lost every
            // counterbore and shipped φ11 through holes instead.
            var loops = new List<object>();          // 外轮廓 / 窗口 / 腰形槽
            var circles = new List<Dictionary<string, object>>();
            foreach (object o in segs)
            {
                var s = (Dictionary<string, object>)o;
                if (Convert.ToString(s["t"]) != "circle") loops.Add(s);
                else circles.Add(s);
            }

            // 同心的两个圆：大的那个是沉口(mouth)，小的那个是孔身(bore)。
            // 两者绝不能进同一张草图——SolidWorks 会静默丢掉里面的那个。
            var pockets = new List<object>();
            var inner = new List<object>();
            var plain = new List<object>();
            foreach (var s in circles)
            {
                double[] c = Dbl(s["c"]);
                double r = Convert.ToDouble(s["r"]);
                bool hasBigger = false, hasSmaller = false;
                foreach (var s2 in circles)
                {
                    double[] c2 = Dbl(s2["c"]);
                    if (Math.Abs(c2[0] - c[0]) >= 0.01 || Math.Abs(c2[1] - c[1]) >= 0.01) continue;
                    double r2 = Convert.ToDouble(s2["r"]);
                    if (r2 > r + 0.01) hasBigger = true;
                    if (r2 < r - 0.01) hasSmaller = true;
                }
                if (hasSmaller) pockets.Add(s);
                else if (hasBigger) inner.Add(s);
                else plain.Add(s);
            }
            log.Add("loops=" + loops.Count + " through=" + plain.Count + " pocket=" + pockets.Count + " inner=" + inner.Count);

            // ---- the counterbores that exist only in a CALL-OUT ------------
            // "16 × φ6.6 完全贯穿 / 反面 ⌴φ11 ▽6.8" has no second circle in the
            // DWG, so nothing above can see it. It is declared in the segments
            // json instead: {"mouth_dia":11,"depth":6.8,"origins":[[x,y],...]}
            // Those holes get their mouth on the FAR face, against the front
            // pockets, which is what "正反面都有沉头" means.
            var backMouths = new List<object>();
            var backMouthOrigins = new List<double[]>();
            double backCbDepth = 0.0;
            object bcNode;
            if (data.TryGetValue("back_counterbores", out bcNode) && bcNode != null)
            {
                var bc = (Dictionary<string, object>)bcNode;
                backCbDepth = Convert.ToDouble(bc["depth"]);
                double mouthR = Convert.ToDouble(bc["mouth_dia"]) / 2.0;
                foreach (object o in (IList)bc["origins"])
                {
                    double[] c = Dbl(o);
                    var m = new Dictionary<string, object>();
                    m["t"] = "circle";
                    m["c"] = new object[] { c[0], c[1] };
                    m["r"] = mouthR;
                    backMouths.Add(m);
                    backMouthOrigins.Add(c);
                }
                log.Add("back mouths=" + backMouths.Count + " depth=" + backCbDepth);
            }

            // ---- blind holes written only in a CALL-OUT --------------------
            // "4 × φ5 H7 ▽10" is a 10mm deep hole, but the DWG draws a plain
            // circle that looks exactly like a through hole. Only the call-out
            // says where it stops, so the depth has to come in as data.
            var blindOrigins = new List<double[]>();
            double blindDepth = 0.0;
            object bhNode;
            if (data.TryGetValue("blind_holes", out bhNode) && bhNode != null)
            {
                var bh = (Dictionary<string, object>)bhNode;
                blindDepth = Convert.ToDouble(bh["depth"]);
                foreach (object o in (IList)bh["origins"])
                    blindOrigins.Add(Dbl(o));
                log.Add("blind holes=" + blindOrigins.Count + " depth=" + blindDepth);
            }

            Directory.CreateDirectory(outDir);
            sw = new SldWorksClass();
            try { sw.Visible = true; } catch { }

            // A part with this name may still be open from a previous run; a
            // silent SaveAs would then write into a read-only document.
            try
            {
                var open = (object[])sw.GetDocuments();
                if (open != null)
                {
                    foreach (object o in open)
                    {
                        var om = o as IModelDoc2;
                        if (om == null) continue;
                        string ot = om.GetTitle();
                        if (ot != null && ot.StartsWith(name, StringComparison.OrdinalIgnoreCase))
                        {
                            sw.CloseDoc(ot);      // lives on ISldWorks, not IModelDoc2
                            log.Add("closed stale doc " + ot);
                        }
                    }
                }
            }
            catch (Exception ce) { log.Add("close-scan " + ce.Message); }
            string tpl = FindPartTemplate();
            if (tpl == null) throw new Exception("no part template found");
            log.Add("template " + tpl);
            md = sw.NewDocument(tpl, 0, 0, 0) as IModelDoc2;
            if (md == null) throw new Exception("NewDocument null");

            // ---- 每个孔 / 轮廓都带上自己的 z 区间，按边界自动切带 ------------
            // 不带区间的硬编码分层（前 6.8 + 后 8.2）只能表达贯穿孔和两面的沉孔，
            // 表达不了"10mm 深的盲孔"。这里改成给每个元素一个 [z0, z1]，
            // 板厚按所有端点自然切成若干带，每带只画"整段都在这一带里"的元素。
            // 好处：同心异径对天然不会进同一带，盲孔也只是少出现几带而已。
            double frontCb = pockets.Count > 0 ? counterboreDepth : 0.0;
            if (frontCb + backCbDepth >= depth - 1e-6)
                throw new Exception("counterbore depths " + frontCb + " + " + backCbDepth
                                    + " do not fit in " + depth + "mm");
            if (blindDepth > 0 && (blindDepth <= 0 || blindDepth >= depth - 1e-6))
                throw new Exception("blind depth " + blindDepth + " invalid for " + depth + "mm");

            var plates = new List<Dictionary<string, object>>();
            foreach (object o in loops) plates.Add(Plate(o, 0.0, depth));
            foreach (object o in pockets) plates.Add(Plate(o, 0.0, frontCb));
            foreach (object o in inner) plates.Add(Plate(o, frontCb, depth));

            foreach (object o in plain)
            {
                double[] c = Dbl(((Dictionary<string, object>)o)["c"]);
                if (InList(blindOrigins, c)) plates.Add(Plate(o, 0.0, blindDepth));
                else if (InList(backMouthOrigins, c)) plates.Add(Plate(o, 0.0, depth - backCbDepth));
                else plates.Add(Plate(o, 0.0, depth));
            }
            foreach (object m in backMouths) plates.Add(Plate(m, depth - backCbDepth, depth));

            var cuts = new List<double> { 0.0, depth };
            foreach (var p in plates)
            {
                cuts.Add(Convert.ToDouble(p["z0"]));
                cuts.Add(Convert.ToDouble(p["z1"]));
            }
            cuts.Sort();
            var edges = new List<double>();
            foreach (double z in cuts)
                if (edges.Count == 0 || Math.Abs(z - edges[edges.Count - 1]) > 1e-4) edges.Add(z);

            var bandStart = new List<double>();
            var bandThick = new List<double>();
            var bandHoles = new List<List<object>>();
            var bandName = new List<string>();
            string lastSig = null;

            for (int i = 0; i + 1 < edges.Count; i++)
            {
                double a = edges[i], b = edges[i + 1];
                if (b - a <= 1e-6) continue;
                var segsIn = new List<object>();
                var sig = new List<string>();
                for (int k = 0; k < plates.Count; k++)
                {
                    double z0 = Convert.ToDouble(plates[k]["z0"]);
                    double z1 = Convert.ToDouble(plates[k]["z1"]);
                    if (z0 <= a + 1e-6 && z1 >= b - 1e-6)
                    {
                        segsIn.Add(plates[k]["seg"]);
                        sig.Add(k.ToString());
                    }
                }
                string s = string.Join(",", sig.ToArray());
                if (s == lastSig)                       // 与上一带完全相同，合成一次拉伸
                {
                    bandThick[bandThick.Count - 1] = b - bandStart[bandStart.Count - 1];
                    bandName[bandName.Count - 1] = bandName[bandName.Count - 1] + "/" + b;
                    continue;
                }
                bandStart.Add(a); bandThick.Add(b - a); bandHoles.Add(segsIn);
                bandName.Add("z" + a + "~" + b + " (" + sig.Count + "个元素)");
                lastSig = s;
            }

            for (int i = 0; i < bandThick.Count; i++)
            {
                OpenSketch();
                DrawAll(bandHoles[i]);
                int sc = SegCount();
                CloseSketch();
                IFeature feat = Extrude(bandThick[i], bandStart[i]);
                log.Add("band " + bandName[i] + " segs=" + sc + " -> "
                        + (feat == null ? "FAIL" : "ok " + feat.Name));
                if (feat == null) throw new Exception("extrude failed on band " + bandName[i]);
            }

            md.EditRebuild3();
            MassProperty mp = ((IModelDocExtension)md.Extension).CreateMassProperty() as MassProperty;
            double vol = Convert.ToDouble(mp.Volume) * 1e9;
            res["volume_mm3"] = Math.Round(vol, 3);
            res["area_mm2"] = Math.Round(Convert.ToDouble(mp.SurfaceArea) * 1e6, 3);

            try { md.ShowNamedView2("*Isometric", 7); } catch { }
            try { md.ViewZoomtofit2(); } catch { }

            var files = (List<string>)res["files"];
            foreach (string ext in new string[] { "SLDPRT", "STEP", "PNG" })
            {
                string p = Path.Combine(outDir, name + "." + ext);
                try
                {
                    int e1 = 0, w1 = 0;
                    bool ok = ((IModelDocExtension)md.Extension).SaveAs(p,
                        (int)swSaveAsVersion_e.swSaveAsCurrentVersion,
                        (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, ref e1, ref w1);
                    if (ok) files.Add(p); else log.Add("EXPORT " + ext + " err=" + e1);
                }
                catch (Exception e) { log.Add("EXPORT " + ext + " EX " + e.Message); }
            }

            res["ok"] = vol > 0;
        }
        catch (Exception e) { log.Add("FATAL " + e.GetType().Name + ": " + e.Message); }
        return new JavaScriptSerializer().Serialize(res);
    }

    /// <summary>
    /// Render the two big faces of an existing part, so "沉头是不是只做了一个面"
    /// is answered by looking instead of by trusting the volume. Saves
    /// &lt;name&gt;-正面.PNG (looking at z = 0) and &lt;name&gt;-反面.PNG.
    /// </summary>
    public static string Shots(string partPath, string outDir)
    {
        var log = new List<string>();
        var res = new Dictionary<string, object>();
        res["ok"] = false;
        res["files"] = new List<string>();
        res["log"] = log;
        try
        {
            sw = new SldWorksClass();
            try { sw.Visible = true; } catch { }
            int e = 0, w = 0;
            md = sw.OpenDoc6(partPath, (int)swDocumentTypes_e.swDocPART, 1, "", ref e, ref w) as IModelDoc2;
            if (md == null) throw new Exception("OpenDoc6 null, err=" + e);
            Directory.CreateDirectory(outDir);
            string stem = Path.GetFileNameWithoutExtension(partPath);
            var views = new string[] { "*Back", "*Front" };
            var tags = new string[] { "-后视看z0面", "-前视看zmax面" };
            for (int i = 0; i < views.Length; i++)
            {
                md.ShowNamedView2(views[i], i == 0 ? 2 : 1);
                md.ViewZoomtofit2();
                md.EditRebuild3();
                System.Threading.Thread.Sleep(800);
                string p = Path.Combine(outDir, stem + tags[i] + ".PNG");
                int ee = 0, ww = 0;
                bool ok = ((IModelDocExtension)md.Extension).SaveAs(p,
                    (int)swSaveAsVersion_e.swSaveAsCurrentVersion,
                    (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, ref ee, ref ww);
                log.Add(tags[i] + " -> " + (ok ? "ok" : "err " + ee));
                if (ok) ((List<string>)res["files"]).Add(p);
            }
            res["ok"] = ((List<string>)res["files"]).Count == 2;
        }
        catch (Exception ex) { log.Add("FATAL " + ex.Message); }
        return new JavaScriptSerializer().Serialize(res);
    }

    // 一个几何元素 + 它在板厚方向上占据的区间
    static Dictionary<string, object> Plate(object seg, double z0, double z1)
    {
        var d = new Dictionary<string, object>();
        d["seg"] = seg;
        d["z0"] = z0;
        d["z1"] = z1;
        return d;
    }

    static bool InList(List<double[]> list, double[] c)
    {
        foreach (double[] o in list)
            if (Math.Abs(o[0] - c[0]) < 0.01 && Math.Abs(o[1] - c[1]) < 0.01) return true;
        return false;
    }

    // The install year is not assumed: probe every SOLIDWORKS 20xx template dir
    // and take the newest one that actually carries a part template.
    static string FindPartTemplate()
    {
        var hits = new List<string>();
        string[] roots = {
            System.Environment.GetFolderPath(System.Environment.SpecialFolder.CommonApplicationData) + @"\SOLIDWORKS",
            @"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS"
        };
        foreach (string root in roots)
        {
            if (!Directory.Exists(root)) continue;
            foreach (string dir in Directory.GetDirectories(root))
            {
                string t = Path.Combine(dir, @"templates\gb_part.prtdot");
                if (File.Exists(t)) hits.Add(t);
            }
        }
        hits.Sort();
        return hits.Count > 0 ? hits[hits.Count - 1] : null;
    }

    static int SegCount()
    {
        try
        {
            var sk = md.SketchManager.ActiveSketch as ISketch;
            if (sk == null) return -1;
            var segs = (object[])sk.GetSketchSegments();
            return segs == null ? 0 : segs.Length;
        }
        catch (Exception) { return -2; }
    }

    static double VolumeMm3()
    {
        try
        {
            var mp = ((IModelDocExtension)md.Extension).CreateMassProperty() as MassProperty;
            return Convert.ToDouble(mp.Volume) * 1e9;
        }
        catch (Exception) { return -1; }
    }

    // 27-arg FeatureCut4. T1 = swEndCondBlind (0), one direction.
    // flipSide = "flip side to cut", dir = "reverse direction" -- these are two
    // different flags; swapping them cuts away everything except the circles.
    static IFeature Cut(double depthMm, bool flipSide, bool dir, double startOffsetMm, bool flipStart)
    {
        int t0 = startOffsetMm > 0 ? 3 : 0;
        return md.FeatureManager.FeatureCut4(
            true, flipSide, dir,
            0, 0, M(depthMm), 0,
            false, false, false, false, 0, 0,
            false, false, false, false,
            false,
            true, true,
            false, false, true,
            t0, M(startOffsetMm), flipStart, true) as IFeature;
    }

    // Start a sketch on the horizontal face that sits at z = zMm (the top of the
    // first layer). Selecting the real face keeps the extrude free of a start
    // offset, which is what silently dropped the inner contours.
    static bool OpenSketchOnTop(double zMm)
    {
        try
        {
            var pd = md as IPartDoc;
            if (pd == null) return false;
            var bodies = pd.GetBodies2((int)swBodyType_e.swSolidBody, false) as object[];
            if (bodies == null || bodies.Length == 0) return false;
            var body = bodies[0] as IBody2;
            if (body == null) return false;
            md.ClearSelection2(true);
            object[] faces = body.GetFaces() as object[];
            if (faces == null) return false;
            foreach (object fo in faces)
            {
                var face = fo as IFace2;
                if (face == null) continue;
                var surf = face.GetSurface() as ISurface;
                if (surf == null || !surf.IsPlane()) continue;
                double[] pp = surf.PlaneParams as double[];   // nx,ny,nz,px,py,pz
                if (pp == null || pp.Length < 6) continue;
                if (Math.Abs(Math.Abs(pp[2]) - 1.0) > 1e-6) continue;
                if (Math.Abs(Math.Abs(pp[5]) - M(zMm)) > 1e-4) continue;
                if (!((IEntity)face).Select4(false, null)) continue;
                (md.SketchManager as ISketchManager).InsertSketch(true);
                return true;
            }
        }
        catch (Exception) { }
        return false;
    }

    static void OpenSketch()
    {
        md.ClearSelection2(true);
        bool plane = md.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, false, 0, null, 0)
                  || md.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, false, 0, null, 0);
        if (!plane) throw new Exception("plane not selected");
        (md.SketchManager as ISketchManager).InsertSketch(true);
    }

    static void CloseSketch()
    {
        (md.SketchManager as ISketchManager).InsertSketch(true);
    }

    static void DrawAll(IList items)
    {
        ISketchManager skm = md.SketchManager as ISketchManager;
        // Without AddToDB the sketch infers against the solid already sitting on
        // this plane and quietly swallows or merges the circles drawn on top of
        // existing holes.
        bool old = skm.AddToDB;
        skm.AddToDB = true;
        try
        {
            foreach (object o in items)
            {
                var s = (Dictionary<string, object>)o;
                string t = Convert.ToString(s["t"]);
                if (t == "circle")
                {
                    double[] c = Dbl(s["c"]);
                    skm.CreateCircleByRadius(M(c[0]), M(c[1]), 0, M(Convert.ToDouble(s["r"])));
                }
                else if (t == "arc")
                {
                    double[] a = Dbl(s["a"]), b = Dbl(s["b"]), m = Dbl(s["m"]);
                    // (start, end, a point on the arc); the other order mirrors it.
                    skm.Create3PointArc(M(a[0]), M(a[1]), 0, M(b[0]), M(b[1]), 0, M(m[0]), M(m[1]), 0);
                }
                else
                {
                    double[] a = Dbl(s["a"]), b = Dbl(s["b"]);
                    skm.CreateLine(M(a[0]), M(a[1]), 0, M(b[0]), M(b[1]), 0);
                }
            }
        }
        finally { skm.AddToDB = old; }
    }

    static IFeature Extrude(double depthMm, double startOffsetMm)
    {
        int t0 = startOffsetMm > 0 ? 3 : 0;
        return md.FeatureManager.FeatureExtrusion3(true, false, false,
            0, 0, M(depthMm), 0,
            false, false, false, false, 0, 0,
            false, false, false, false,
            true, true, true, t0, M(startOffsetMm), false) as IFeature;
    }

    // Sketch space is metres.
    static double M(double mm) { return mm / 1000.0; }

    static double[] Dbl(object o)
    {
        var arr = (IList)o;
        return new double[] { Convert.ToDouble(arr[0]), Convert.ToDouble(arr[1]) };
    }
}
