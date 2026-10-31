# Replay a pdf2cad2.py plan (CAD-mm coords + bulge arcs) into AutoCAD, save DWG+DXF.
# Pure ASCII source.
#   powershell -NoProfile -STA -ExecutionPolicy Bypass -File replay2.ps1 -PlanPath plan2.json -Out out.dwg [-Visible]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$Out,
    [switch]$Visible,
    [string]$PlotPdf = ""
)
$ErrorActionPreference = "Continue"
$log = [System.IO.Path]::ChangeExtension($Out, ".log.txt")
$logDir = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($log))
if (-not (Test-Path $logDir)) { $null = New-Item -ItemType Directory -Path $logDir -Force }
function L($m) { Add-Content -Path $log -Value $m -Encoding UTF8 }
"=== replay2 start ===" | Set-Content -Path $log -Encoding UTF8

$sw = [System.Diagnostics.Stopwatch]::StartNew()

# NOTE: variable named $pl, NOT $plan -- a param of the same name (case
# insensitive) carries a [string] constraint that would coerce this object.
$raw = Get-Content -Path $PlanPath -Raw -Encoding UTF8
$pl = $raw | ConvertFrom-Json
L ("entities: circles=" + $pl.circles.Count + " polylines=" + $pl.polylines.Count + " texts=" + $pl.texts.Count)

$acad = $null
foreach ($progId in @("AutoCAD.Application.25", "AutoCAD.Application")) {
    try { $acad = New-Object -ComObject $progId; break } catch { L "FAIL $progId : $($_.Exception.Message)" }
}
if ($null -eq $acad) { L "[X] no connection"; exit 1 }
L "connected $($acad.Version)"
try { $acad.Visible = [bool]$Visible } catch { }

$doc = $acad.Documents.Add()
L "doc: $($doc.Name)"

$defs = @(
    @{ n = "0-OUTLINE"; c = 7; lw = 50 },
    @{ n = "0-THIN";    c = 8; lw = 13 },
    @{ n = "0-FILL";    c = 9; lw = 9  },
    @{ n = "0-TEXT";    c = 7; lw = 13 }
)
foreach ($d in $defs) {
    try { $null = $doc.Layers.Add($d.n) } catch { }
    try { $doc.Layers.Item($d.n).color = $d.c } catch { }
    try { $doc.Layers.Item($d.n).Lineweight = $d.lw } catch { }
}
L "layers ready"

try {
    $null = $doc.TextStyles.Add("HZ")
} catch { }
try {
    $ts = $doc.TextStyles.Item("HZ")
    $ts.fontFile = "C:\Windows\Fonts\simsun.ttc"
    $doc.ActiveTextStyle = $ts
    L "text style HZ -> simsun.ttc"
} catch { L "textstyle FAIL: $($_.Exception.Message)" }

$ms = $doc.ModelSpace
function D3($x, $y, $z) { $a = New-Object 'double[]' 3; $a[0] = $x; $a[1] = $y; $a[2] = $z; return , $a }

$nc = 0; $np = 0; $nt = 0; $err = 0; $retry = 0

# ---------- circles ----------
L "modelspace before = $($ms.Count)"
foreach ($c in $pl.circles) {
    $done = $false
    for ($t = 0; $t -lt 4 -and -not $done; $t++) {
        try {
            $e = $ms.AddCircle((D3 ([double]$c.c[0]) ([double]$c.c[1]) 0), [double]$c.r)
            $e.Layer = "0-" + $c.layer
            $done = $true; $nc++
        } catch {
            if ($_.Exception.Message -match "80010001|拒绝接收") { $retry++; Start-Sleep -Milliseconds 150 }
            else { $err++; if ($err -le 5) { L ("circle FAIL: " + $_.Exception.Message) }; $done = $true }
        }
    }
}
L "circles: $nc  (err=$err retry=$retry)  ms=$($ms.Count)"

# ---------- polylines ----------
foreach ($p in $pl.polylines) {
    $pts = $p.pts
    $n = $pts.Count
    if ($n -lt 2) { continue }
    $closed = [bool]$p.closed
    $bul = $p.bul
    if ($null -eq $bul) { $bul = @() }

    $done = $false
    for ($t = 0; $t -lt 4 -and -not $done; $t++) {
        try {
            if ($n -eq 2) {
                $e = $ms.AddLine((D3 ([double]$pts[0][0]) ([double]$pts[0][1]) 0),
                                 (D3 ([double]$pts[1][0]) ([double]$pts[1][1]) 0))
            } else {
                $co = New-Object 'double[]' ($n * 2)
                for ($i = 0; $i -lt $n; $i++) {
                    $co[2 * $i] = [double]$pts[$i][0]
                    $co[2 * $i + 1] = [double]$pts[$i][1]
                }
                $e = $ms.AddLightWeightPolyline($co)
                if ($closed) { $e.Closed = $true }
                $nb = [Math]::Min($bul.Count, $n)
                for ($i = 0; $i -lt $nb; $i++) {
                    $bv = [double]$bul[$i]
                    if ([Math]::Abs($bv) -gt 1e-9) {
                        try { $e.SetBulge($i, $bv) } catch { L "SetBulge FAIL i=$i : $($_.Exception.Message)" }
                    }
                }
            }
            $e.Layer = "0-" + $p.layer
            $done = $true; $np++
        } catch {
            if ($_.Exception.Message -match "80010001|拒绝接收") { $retry++; Start-Sleep -Milliseconds 150 }
            else { $err++; if ($err -le 10) { L ("poly FAIL n=$n : " + $_.Exception.Message) }; $done = $true }
        }
    }
}
L "polylines: $np  (err=$err retry=$retry)  ms=$($ms.Count)"

# ---------- texts ----------
foreach ($t2 in $pl.texts) {
    $txt = [string]$t2.t
    if ([string]::IsNullOrWhiteSpace($txt)) { continue }
    $done = $false
    for ($t = 0; $t -lt 4 -and -not $done; $t++) {
        try {
            $h = [double]$t2.h
            if ($h -le 0) { $h = 2.5 }
            $e = $ms.AddText($txt, (D3 ([double]$t2.p[0]) ([double]$t2.p[1]) 0), $h)
            try {
                if ($null -ne $t2.rot -and [double]$t2.rot -ne 0) { $e.Rotation = [double]$t2.rot }
            } catch { }
            try {
                # COM name is ScaleFactor (WidthFactor is the .NET API name)
                if ($null -ne $t2.wf) { $e.ScaleFactor = [double]$t2.wf }
            } catch { $err++; if ($err -le 20) { L ("scalefactor FAIL [" + $txt + "]: " + $_.Exception.Message) } }
            $e.Layer = "0-TEXT"
            $done = $true; $nt++
        } catch {
            if ($_.Exception.Message -match "80010001|拒绝接收") { $retry++; Start-Sleep -Milliseconds 150 }
            else { $err++; if ($err -le 15) { L ("text FAIL [" + $txt + "]: " + $_.Exception.Message) }; $done = $true }
        }
    }
}
L "texts: $nt  (err=$err retry=$retry)"

L ("ModelSpace count = " + $ms.Count)
$sw.Stop()
L ("draw time = " + [Math]::Round($sw.Elapsed.TotalSeconds, 2) + " s")

# ---------- save ----------
$full = [System.IO.Path]::GetFullPath($Out)
$dir = [System.IO.Path]::GetDirectoryName($full)
if (-not (Test-Path $dir)) { $null = New-Item -ItemType Directory -Path $dir -Force }
if (Test-Path $full) { Remove-Item $full -Force -ErrorAction SilentlyContinue }
try {
    $doc.SaveAs($full)
    $fi = [System.IO.FileInfo]$full
    L ("saved DWG: " + $full + "  size=" + $(if ($fi.Exists) { $fi.Length } else { 0 }))
} catch { L "SaveAs FAIL: $($_.Exception.Message)" }

$dxf = [System.IO.Path]::ChangeExtension($full, ".dxf")
if (Test-Path $dxf) { Remove-Item $dxf -Force -ErrorAction SilentlyContinue }
try {
    $doc.SendCommand("FILEDIA`n0`n")
    $doc.SendCommand("_DXFOUT`n$dxf`n`n")
} catch { L "DXFOUT FAIL: $($_.Exception.Message)" }
try { $doc.SendCommand("_.ZOOM`n_E`n") } catch { }
Start-Sleep -Milliseconds 1200
$dx = [System.IO.FileInfo]$dxf
L ("dxf exists=" + $dx.Exists + " size=" + $(if ($dx.Exists) { $dx.Length } else { 0 }))

try { $doc.Saved = $true } catch { }

# ---------- optional plot to PDF (true CAD render for visual verification) ----------
if ($PlotPdf -ne "") {
    try {
        if (Test-Path $PlotPdf) { Remove-Item $PlotPdf -Force -ErrorAction SilentlyContinue }
        # background plotting returns immediately and never writes the file
        try { $doc.SetVariable("BACKGROUNDPLOT", 0) } catch { L "bgplot FAIL" }
        $layout = $doc.ActiveLayout
        $layout.ConfigName = "DWG To PDF.pc3"
        try { $layout.CanonicalMediaName = "ISO_A2_(594.00_x_420.00_MM)" } catch { L "media FAIL: $($_.Exception.Message)" }
        $layout.PlotType = 1
        $layout.CenterPlot = $true
        $layout.PlotRotation = 0
        $layout.UseStandardScale = $true
        $layout.StandardScale = 0
        $layout.PlotWithPlotStyles = $true
        $layout.PlotWithLineweights = $true
        $doc.Plot.PlotToFile($PlotPdf)
        Start-Sleep -Milliseconds 2000
        $pf = [System.IO.FileInfo]$PlotPdf
        L ("plot pdf exists=" + $pf.Exists + " size=" + $(if ($pf.Exists) { $pf.Length } else { 0 }))
    } catch { L "plot FAIL: $($_.Exception.Message)" }
}

if (-not $Visible) {
    try { $acad.Quit(); L "quit" } catch { L "quit FAIL: $($_.Exception.Message)" }
} else { L "left AutoCAD open" }
L "=== replay2 done ==="
