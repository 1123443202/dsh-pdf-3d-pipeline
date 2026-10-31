param(
    # Relative defaults resolve against the CALLER's cwd, so the skill can be
    # run from the folder that holds the drawing instead of the skill folder.
    [string]$Segments = '.\part_segments.json',
    [string]$OutDir = '.\out',
    [string]$Name = 'TEST',
    [double]$CounterboreDepth = 6.8,
    [switch]$KeepOpen
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($Segments)) {
    $Segments = Join-Path (Get-Location).Path $Segments
}
if (-not (Test-Path $Segments)) { throw "segments file not found: $Segments" }
if (-not [System.IO.Path]::IsPathRooted($OutDir)) {
    $OutDir = Join-Path (Get-Location).Path $OutDir
}

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
try { Add-Type -Path (Join-Path $here 'DwgBuild.cs') -ReferencedAssemblies $refs -ErrorAction Stop }
catch { if ($_.Exception.Message -notmatch 'already exists') { throw } }

[DwgBuild]::Build($Segments, $OutDir, $Name, $CounterboreDepth) | Write-Output

if (-not $KeepOpen) {
    Start-Sleep -Milliseconds 1500
    Get-Process SLDWORKS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}
