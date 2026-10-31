# run.ps1 - one entry point for the whole PDF -> DWG -> SolidWorks -> verify -> deliver chain.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 preflight
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 spec  -Pdf .\part.pdf
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 dwg   -Pdf .\part.pdf -PartWidth 700 -Dwg .\part.dwg
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 part  -Dxf .\part.dxf -Depth 15 -Mass 4.87
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 build -Dxf .\part.dxf -Depth 15 -Name PART -Counterbore 6.8
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 verify -Step .\out\PART.STEP -Part .\out\PART.SLDPRT
#   powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 deliver -Step .\out\PART.STEP -To D:\deliver
#
# Every stage ends with a machine-readable verdict:
#     GATE <stage>: PASS
#     GATE <stage>: FAIL
#     STOP: <what to fix>
# Exit codes: 0 pass, 1 gate failed, 2 missing input.
#
# The point of this file: an agent (or a person) never has to remember which
# script to call with which arguments, and can never "skip" a gate by accident.
param(
    [Parameter(Position = 0)]
    [ValidateSet('preflight', 'spec', 'dwg', 'part', 'thickness', 'build', 'verify', 'deliver')]
    [string]$Stage = 'preflight',

    [string]$Pdf,
    [string]$Spec = '.\drawing_spec.json',
    [string]$Plan = '.\plan.json',
    [string]$Dwg,
    [string]$Dxf,
    [double]$PartWidth = 0,
    [double]$Depth = 15,
    [double]$Mass = 0,
    [string]$Material = 'aluminium',
    [string]$Segments = '.\part_segments.json',
    [string]$Step,
    [string]$Part,
    [string]$OutDir = '.\out',
    [string]$Name = 'PART',
    [double]$Counterbore = 6.8,
    [string]$To,
    [switch]$Visible,
    [switch]$KeepOpen
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$scripts = Join-Path $root 'scripts'
if (-not (Test-Path (Join-Path $scripts 'drawing_spec.py'))) { $scripts = $root }
. (Join-Path $scripts 'env.ps1')
$E = Get-PipelineEnv
$S = $E.S
$PY = $E.PY

function Say($m) { Write-Output $m }
function Head($m) { Say ''; Say "=== $m ===" }
function Gate($name, $ok, $msg) {
    if ($ok) { Say "GATE ${name}: PASS"; return }
    Say "GATE ${name}: FAIL"
    Say "STOP: $msg"
    exit 1
}
function Need($path, $what) {
    if (-not $path) { Say "STOP: $what is required for stage '$Stage'"; exit 2 }
    if (-not (Test-Path -LiteralPath $path)) { Say "STOP: $what not found: $path"; exit 2 }
}
function Abs($p) {
    if (-not $p) { return $p }
    if ([System.IO.Path]::IsPathRooted($p)) { return $p }
    return (Join-Path (Get-Location).Path $p)
}
function NeedPy {
    if (-not $PY) { Say 'STOP: no python 3 found. Set PDF3D_PYTHON=<path to python.exe>'; exit 2 }
}

Switch ($Stage) {

    'preflight' {
        Head 'preflight'
        & (Join-Path $S 'selftest.ps1')
        Gate 'preflight' ($LASTEXITCODE -eq 0) 'fix every BLOCK line above before building anything'
    }

    'spec' {
        Head 'spec  (PDF call-outs -> drawing_spec.json)'
        NeedPy
        Need $Pdf 'Pdf'
        $Spec = Abs $Spec
        & $PY (Join-Path $S 'drawing_spec.py') $Pdf $Spec
        $code = $LASTEXITCODE
        $probe = @'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
u = d.get('unparsed') or []
print('call-outs=%d  holes=%d  unparsed=%d' % (len(d.get('holes') or []), d.get('total_holes') or 0, len(u)))
for x in u:
    print('  UNPARSED: %s' % x)
sys.exit(0 if (not u and d.get('holes')) else 1)
'@
        $probeFile = Join-Path $env:TEMP 'pdf3d_probe_spec.py'
        Set-Content -LiteralPath $probeFile -Value $probe -Encoding UTF8
        & $PY $probeFile $Spec
        $ok = ($LASTEXITCODE -eq 0) -and ($code -eq 0)
        Gate 'spec' $ok 'read the UNPARSED lines and extend drawing_spec.py; never build on a partial call-out list'
    }

    'dwg' {
        Head 'dwg  (PDF -> DWG/DXF)'
        NeedPy
        Need $Pdf 'Pdf'
        if (-not $Dwg) { $Dwg = [System.IO.Path]::ChangeExtension((Abs $Pdf), '.dwg') }
        $Dwg = Abs $Dwg
        $Plan = Abs $Plan
        $pw = @()
        if ($PartWidth -gt 0) { $pw = @('--part-width', "$PartWidth") }
        & $PY (Join-Path $S 'pdf2cad2.py') $Pdf $Plan @pw --texts dim
        if ($LASTEXITCODE -ne 0) { Say 'STOP: pdf2cad2.py failed (see output above)'; exit 1 }
        $rargs = @('-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $S 'replay2.ps1'),
                   '-PlanPath', $Plan, '-Out', $Dwg)
        if ($Visible) { $rargs += '-Visible' }
        & powershell @rargs
        $dxf = [System.IO.Path]::ChangeExtension($Dwg, '.dxf')
        $ok = (Test-Path -LiteralPath $Dwg) -and (Test-Path -LiteralPath $dxf) -and
              ((Get-Item -LiteralPath $dxf).Length -gt 4096)
        if (-not $ok) { Say "  dwg=$Dwg  dxf=$dxf  (log: $([System.IO.Path]::ChangeExtension($Dwg, '.log.txt')))" }
        Gate 'dwg' $ok 'AutoCAD must be running; check the .log.txt next to the DWG'
    }

    'part' {
        Head 'part  (DWG/DXF -> part geometry + mass check)'
        NeedPy
        $src = $Dxf; if (-not $src) { $src = $Dwg }
        Need $src 'Dxf (or Dwg)'
        $outDxf = Join-Path (Get-Location).Path ("${Name}.part.dxf")
        $lines = & $PY (Join-Path $S 'part_from_dxf.py') $src $Depth $outDxf 2>&1
        $lines | ForEach-Object { Say $_ }
        $txt = ($lines | Out-String)
        $hasLoop = $txt -match 'outer loop'
        $m = [regex]::Match($txt, 'mass\([^)]*\)\s*=\s*([0-9.]+)\s*kg')
        $ok = $hasLoop
        if ($Mass -gt 0 -and $m.Success) {
            $got = [double]$m.Groups[1].Value
            $dev = [math]::Abs($got / $Mass - 1.0) * 100.0
            Say ("  mass {0:N3} kg vs drawing {1:N3} kg  ({2:N2}%)" -f $got, $Mass, $dev)
            $ok = $ok -and ($dev -le 1.0)
        }
        Gate 'part' $ok 'outer loop must equal the drawing outline and mass must be within 1%; otherwise the wrong geometry was picked'
    }

    'thickness' {
        Head 'thickness  (back-calculate plate thickness from drawing mass)'
        NeedPy
        $src = $Dxf; if (-not $src) { $src = $Dwg }
        Need $src 'Dxf (or Dwg)'
        if ($Mass -le 0) { Say 'STOP: -Mass <kg printed on the drawing> is required'; exit 2 }
        $lines = & $PY (Join-Path $S 'estimate_thickness.py') $src $Mass --material $Material 2>&1
        $lines | ForEach-Object { Say $_ }
        $ok = (($lines | Out-String) -match 'RESULT: use thickness')
        Gate 'thickness' $ok 'no stock thickness reproduces the drawing mass: the geometry is wrong, do not tweak thickness'
    }

    'build' {
        Head 'build  (geometry + call-outs -> SLDPRT/STEP/PNG)'
        NeedPy
        $Segments = Abs $Segments
        $Spec = Abs $Spec
        $src = $Dxf; if (-not $src) { $src = $Dwg }
        if ($src) {
            $src = Abs $src
            # only the chosen part DXF feeds the geometry; the sheet DXF would pull in the frame
            & $PY (Join-Path $S 'part_segments.py') $src $Segments $Depth
            if ($LASTEXITCODE -ne 0) { Say 'STOP: part_segments.py failed'; exit 1 }
        } elseif (-not (Test-Path -LiteralPath $Segments)) {
            Say "STOP: need either -Dxf <part.dxf> or an existing $Segments"; exit 2
        }
        if (Test-Path -LiteralPath $Spec) {
            & $PY (Join-Path $S 'apply_spec.py') $Segments $Spec
            Gate 'build.spec' ($LASTEXITCODE -eq 0) 'apply_spec.py could not match the call-out counts to the geometry; fix the diameters or the call-out, do not guess'
        } else {
            Say "  (no $Spec - skipping apply_spec; counterbores written only in call-outs will be missing)"
        }
        $OutDir = Abs $OutDir
        if (-not $PSBoundParameters.ContainsKey('Counterbore')) {
            Say '  note: -Counterbore not given, defaulting to 6.8 mm (front face only).'
            Say '        Pass the depth printed in the call-out, or verify.spec will fail if it differs.'
        }
        $lines = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $S 'build_from_dwg.ps1') `
            -Segments $Segments -OutDir $OutDir -Name $Name -CounterboreDepth $Counterbore 2>&1
        $lines | ForEach-Object { Say $_ }
        $json = ($lines | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
        $ok = $false; $vol = 0
        if ($json) {
            try {
                $j = $json | ConvertFrom-Json
                $ok = [bool]$j.ok
                $vol = [double]$j.volume_mm3
            } catch { $ok = $false }
            # keep the build log next to the model: deliver/make_report.py reads it
            Set-Content -LiteralPath (Join-Path $OutDir "${Name}.build.json") -Value $json -Encoding UTF8
        }
        # anti-counterfeit: every band must report the same element count it drew
        $bandBad = 0
        foreach ($ln in $lines) {
            $bm = [regex]::Match("$ln", 'band z([0-9.]+)~([0-9.]+) \(([0-9]+)[^)]*segs=([0-9]+)')
            if ($bm.Success -and $bm.Groups[3].Value -ne $bm.Groups[4].Value) { $bandBad++ }
        }
        if ($bandBad -gt 0) { Say "  WARNING: $bandBad band(s) drew fewer sketch entities than planned - circles were swallowed (AddToDB)" }
        Say ("  volume {0:N1} mm3" -f $vol)
        Gate 'build' ($ok -and $vol -gt 1000 -and $bandBad -eq 0) 'extrude reported failure, zero volume, or a band lost circles; read the band lines above'
    }

    'verify' {
        Head 'verify  (call-outs -> geometry, 4 gates)'
        NeedPy
        Need $Step 'Step'
        Need $Spec 'Spec'
        $Step = Abs $Step; $Spec = Abs $Spec; $Segments = Abs $Segments

        & $PY (Join-Path $S 'spec_verify.py') $Spec $Step
        Gate 'verify.spec' ($LASTEXITCODE -eq 0) 'the model does not match the call-outs. Nothing else counts until this passes'

        & $PY (Join-Path $S 'hole_audit.py') $Step $Segments
        Gate 'verify.holes' ($LASTEXITCODE -eq 0) 'holes disagree with the DWG (position / diameter / counterbore face)'

        & $PY (Join-Path $S 'depth_check.py') $Step
        Gate 'verify.depth' ($LASTEXITCODE -eq 0) 'a counterbore mouth floats inside the plate instead of sitting on a face'

        $p = $Part
        if (-not $p) {
            $p = Join-Path $OutDir ("${Name}.SLDPRT")
            if (-not (Test-Path -LiteralPath $p)) {
                $p = (Get-ChildItem -Path (Get-Location).Path -Filter '*.SLDPRT' -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
            }
        }
        if ($p -and (Test-Path -LiteralPath $p)) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $S 'views.ps1') -Part (Abs $p) -OutDir (Abs $OutDir)
            Gate 'verify.views' ($LASTEXITCODE -eq 0) 'could not export the two face views; look at both images before delivering'
        } else {
            Say '  (no SLDPRT given - skipped face views; the two images are the only human-checkable evidence)'
        }
        Gate 'verify' $true ''
    }

    'deliver' {
        Head 'deliver'
        NeedPy
        Need $Step 'Step'
        if (-not $To) { Say "STOP: -To <delivery folder> is required"; exit 2 }
        $Step = Abs $Step; $To = Abs $To
        $Spec = Abs $Spec
        if (Test-Path -LiteralPath $Spec) {
            & $PY (Join-Path $S 'spec_verify.py') $Spec $Step
            Gate 'deliver.spec' ($LASTEXITCODE -eq 0) 'refusing to deliver a model that fails the call-out check'
        }
        if (-not (Test-Path -LiteralPath $To)) { New-Item -ItemType Directory -Path $To -Force | Out-Null }
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($Step)
        $dir = [System.IO.Path]::GetDirectoryName($Step)
        $copied = 0
        Get-ChildItem -Path $dir -Filter "${stem}.*" -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.SLDPRT', '.STEP', '.PNG') } |
            ForEach-Object { Copy-Item $_.FullName $To -Force; $copied++ }
        Get-ChildItem -Path $dir -Filter "${stem}-*.PNG" -File -ErrorAction SilentlyContinue |
            ForEach-Object { Copy-Item $_.FullName $To -Force; $copied++ }
        if (Test-Path -LiteralPath $Spec) { Copy-Item $Spec $To -Force; $copied++ }
        if (Test-Path -LiteralPath $Segments) { Copy-Item $Segments $To -Force; $copied++ }

        if ($Mass -gt 0 -and (Test-Path -LiteralPath $Spec)) {
            $bj = Join-Path $dir "${stem}.build.json"
            $rargs2 = @('--spec', $Spec, '--step', $Step, '--segments', $Segments,
                        '--drawing-mass', "$Mass", '--out', $To, '--name', $stem)
            if (Test-Path -LiteralPath $bj) { $rargs2 += @('--build-json', $bj) }
            & $PY (Join-Path $S 'make_report.py') @rargs2
        }
        Gate 'deliver' ($copied -ge 3) 'fewer than 3 files copied - check -Step / -To'
    }
}
