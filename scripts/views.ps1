param(
    [string]$Part = '.\*.SLDPRT',
    [string]$OutDir = '.'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 没给具体零件就取目录里最新的那个
if (-not (Test-Path $Part)) {
    $Part = (Get-ChildItem -Path (Join-Path (Get-Location).Path '*.SLDPRT') |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    if (-not $Part) { throw "目录里没有 .SLDPRT" }
}
$Part = (Resolve-Path $Part).Path
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path (Get-Location).Path $OutDir }

$redist = 'C:\sw2025\SOLIDWORKS\api\redist'
if (-not (Test-Path "$redist\SolidWorks.Interop.sldworks.dll")) {
    $redist = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist'
}
[void][System.Reflection.Assembly]::LoadFrom("$redist\SolidWorks.Interop.sldworks.dll")
[void][System.Reflection.Assembly]::LoadFrom("$redist\SolidWorks.Interop.swconst.dll")
$refs = @("$redist\SolidWorks.Interop.sldworks.dll", "$redist\SolidWorks.Interop.swconst.dll",
          'System.dll', 'System.Web.Extensions.dll')
try { Add-Type -Path (Join-Path $here 'DwgBuild.cs') -ReferencedAssemblies $refs -ErrorAction Stop }
catch { if ($_.Exception.Message -notmatch 'already exists') { throw } }

[DwgBuild]::Shots($Part, $OutDir) | Write-Output

Start-Sleep -Milliseconds 800
Get-Process SLDWORKS -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
