param(
    # resolves against the caller's cwd, like build_from_dwg.ps1
    [string]$Segments = '.\part_segments.json',
    [double]$Depth = 15,
    [string]$MaxList = '68,72,76,80,84,88,92,96,100,104,108'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($Segments)) {
    $Segments = Join-Path (Get-Location).Path $Segments
}
if (-not (Test-Path $Segments)) { throw "segments file not found: $Segments" }

$redist = 'C:\sw2025\SOLIDWORKS\api\redist'
if (-not (Test-Path "$redist\SolidWorks.Interop.sldworks.dll")) {
    $redist = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist'
}
[void][System.Reflection.Assembly]::LoadFrom("$redist\SolidWorks.Interop.sldworks.dll")
[void][System.Reflection.Assembly]::LoadFrom("$redist\SolidWorks.Interop.swconst.dll")

$refs = @(
    "$redist\SolidWorks.Interop.sldworks.dll",
    "$redist\SolidWorks.Interop.swconst.dll",
    'System.dll', 'System.Web.Extensions.dll'
)
try { Add-Type -Path (Join-Path $here 'Bisect.cs') -ReferencedAssemblies $refs -ErrorAction Stop }
catch { if ($_.Exception.Message -notmatch 'already exists') { throw } }

[Bisect]::Run($Segments, $Depth, $MaxList) | Write-Output

Start-Sleep -Milliseconds 1200
Get-Process SLDWORKS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
