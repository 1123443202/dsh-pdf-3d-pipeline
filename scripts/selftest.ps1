# Pre-flight for the pdf-to-3d pipeline. Read-only: starts nothing, draws nothing.
#   powershell -NoProfile -ExecutionPolicy Bypass -File selftest.ps1
# Exit 0 = ready. Exit 1 = at least one blocking problem (listed as BLOCK).
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'env.ps1')
$block = 0
function Ok($m)   { Write-Output "  OK    $m" }
function Warn($m) { Write-Output "  WARN  $m" }
function Bad($m)  { Write-Output "  BLOCK $m"; $script:block++ }

Write-Output "== scripts =="
$need = @('pdf2cad2.py', 'replay2.ps1', 'part_from_dxf.py', 'part_segments.py',
          'estimate_thickness.py', 'dxf_geom.py', 'DwgBuild.cs', 'build_from_dwg.ps1',
          'drawing_spec.py', 'apply_spec.py', 'spec_verify.py', 'pyml.py', 'env.ps1',
          'make_report.py', 'add_back_cbore.py', 'step_geom.py', 'hole_audit.py',
          'depth_check.py', 'views.ps1')
$missing = @()
foreach ($f in $need) {
    if (-not (Test-Path (Join-Path $here $f))) { $missing += $f }
}
if ($missing.Count -eq 0) { Ok "all $($need.Count) scripts present" }
else { Bad ("missing: " + ($missing -join ', ')) }

Write-Output "== python =="
$E = Get-PipelineEnv
$PY = $E.PY
if ($PY) {
    $v = & $PY -c "import sys;print(sys.version.split()[0])" 2>&1
    Ok "interpreter $v  $PY"
    if ($E.PyMuOk) {
        Ok "pymupdf loads (step 1 dependency)"
    } elseif ($E.PyMuDir) {
        Bad "pymupdf not importable, but libs exist at $($E.PyMuDir) - set PYMUPDF_PATH"
    } else {
        Bad "pymupdf missing: & `"$PY`" -m pip install pymupdf"
    }
} else {
    Bad "no python 3 interpreter found; set PDF3D_PYTHON=<path to python.exe>"
}

Write-Output "== AutoCAD =="
if ($E.AcadPid) { Ok "running, PID $($E.AcadPid)" } else { Bad "not running - step 1 replay needs it" }

Write-Output "== SolidWorks =="
if ($E.SWRedist) { Ok "interop at $($E.SWRedist)" }
else { Bad "SolidWorks interop DLL not found" }

if ($E.Template) { Ok "part template $($E.Template)" } else { Warn "no gb_part.prtdot; DwgBuild falls back to Part.prtdot" }

Write-Output "== rules reminder =="
Write-Output "  - never call bare 'python' (Microsoft Store stub, exits 9009 silently)"
Write-Output "  - step 1A: drawing_spec.py must parse every hole call-out (unparsed empty)"
Write-Output "  - step 2 mass must match the drawing within 1% before starting SolidWorks"
Write-Output "  - the DWG is the whole sheet; part_from_dxf.py must pick the part out of it"
Write-Output "  - step 5 gate #1: spec_verify.py must say 0 problems - volume/mass cannot prove a hole"

Write-Output "----------------------------------------------------------"
if ($block -eq 0) { Write-Output "RESULT: ready"; exit 0 }
else { Write-Output "RESULT: $block blocking problem(s)"; exit 1 }
