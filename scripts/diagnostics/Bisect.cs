using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

/// <summary>
/// Extrude the same part with progressively more segments (loops first, then
/// holes) to find the exact segment that makes the base extrude fail.
/// </summary>
public static class Bisect
{
    public static string Run(string segPath, double depthMm, string maxList)
    {
        var log = new List<string>();
        var res = new Dictionary<string, object>();
        res["cases"] = new List<string>();

        var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            File.ReadAllText(segPath, Encoding.UTF8));
        var segs = (IList)data["segments"];

        string[] parts = maxList.Split(',');
        ISldWorks sw = new SldWorksClass();
        try { sw.Visible = true; } catch { }
        string tpl = @"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot";

        foreach (string ps in parts)
        {
            int maxSeg = Convert.ToInt32(ps.Trim());
            string tag = "n<=" + maxSeg;
            try
            {
                IModelDoc2 md = sw.NewDocument(tpl, 0, 0, 0) as IModelDoc2;
                md.ClearSelection2(true);
                md.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, false, 0, null, 0);
                ISketchManager skm = md.SketchManager as ISketchManager;
                skm.InsertSketch(true);

                int drawn = 0, circles = 0;
                for (int i = 0; i < segs.Count && drawn < maxSeg; i++)
                {
                    var s = (Dictionary<string, object>)segs[i];
                    string t = Convert.ToString(s["t"]);
                    if (t == "circle")
                    {
                        double[] cc = Dbl(s["c"]);
                        skm.CreateCircleByRadius(cc[0] / 1000, cc[1] / 1000, 0, Convert.ToDouble(s["r"]) / 1000);
                        circles++;
                    }
                    else if (t == "arc")
                    {
                        double[] a = Dbl(s["a"]), b = Dbl(s["b"]), m = Dbl(s["m"]);
                        skm.Create3PointArc(a[0] / 1000, a[1] / 1000, 0, b[0] / 1000, b[1] / 1000, 0, m[0] / 1000, m[1] / 1000, 0);
                    }
                    else
                    {
                        double[] a = Dbl(s["a"]), b = Dbl(s["b"]);
                        skm.CreateLine(a[0] / 1000, a[1] / 1000, 0, b[0] / 1000, b[1] / 1000, 0);
                    }
                    drawn++;
                }
                skm.InsertSketch(true);

                IFeature feat = md.FeatureManager.FeatureExtrusion3(true, false, false,
                    0, 0, depthMm / 1000.0, 0,
                    false, false, false, false, 0, 0,
                    false, false, false, false,
                    true, true, true, 0, 0, false) as IFeature;

                double vol = 0;
                if (feat != null)
                {
                    md.EditRebuild3();
                    MassProperty mp = ((IModelDocExtension)md.Extension).CreateMassProperty() as MassProperty;
                    vol = Math.Round(Convert.ToDouble(mp.Volume) * 1e9, 1);
                }
                string line = tag + ": drawn=" + drawn + " circles=" + circles + " -> "
                            + (feat == null ? "EXTRUDE FAIL" : "ok vol=" + vol);
                log.Add(line);
                ((List<string>)res["cases"]).Add(line);
                sw.CloseDoc(md.GetTitle());
            }
            catch (Exception e)
            {
                log.Add(tag + " EX " + e.GetType().Name + ": " + e.Message);
            }
        }
        res["ok"] = true;
        res["log"] = log;
        return new JavaScriptSerializer().Serialize(res);
    }

    static double[] Dbl(object o)
    {
        var arr = (IList)o;
        return new double[] { Convert.ToDouble(arr[0]), Convert.ToDouble(arr[1]) };
    }
}
