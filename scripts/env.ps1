# env.ps1 - resolve everything the pipeline needs, without hardcoded user paths.
#
#   . "$PSScriptRoot\env.ps1"
#   $E = Get-PipelineEnv          # $E.PY $E.S $E.SWRedist $E.AddinsOk $E.TemplateOk
#
# Why this file exists: the skill used to hardcode
#   C:\Users\<somebody>\.dsh\dsh-runtimes\...\python.exe
# which is unportable and silently fatal (the Store stub `python` exits 9009 with
# no message). Every candidate is now *executed* before it is trusted.

$ErrorActionPreference = 'Continue'

function Test-PyExe {
    param([string]$Exe, [switch]$NeedPymu)
    if (-not $Exe) { return $false }
    if (-not (Test-Path -LiteralPath $Exe)) { return $false }
    $out = & $Exe -c "import sys; print(sys.version_info[0])" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }          # the Store stub dies here
    if (("$out").Trim() -ne '3') { return $false }
    if ($NeedPymu) {
        & $Exe -c "import pymupdf" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return $false }
    }
    return $true
}

function Get-PythonCandidates {
    $c = New-Object System.Collections.ArrayList
    foreach ($v in @($env:PDF3D_PYTHON, $env:CADEVAL_PYTHON)) {
        if ($v) { [void]$c.Add($v) }
    }
    [void]$c.Add("$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe")

    $roots = @(
        "$env:USERPROFILE\.workbuddy\binaries\python\versions",
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python*"
    )
    foreach ($r in $roots) {
        Get-ChildItem -Path $r -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $e = Join-Path $_.FullName 'python.exe'
            if (Test-Path -LiteralPath $e) { [void]$c.Add($e) }
        }
    }
    Get-ChildItem -Path 'C:\' -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $e = Join-Path $_.FullName 'python.exe'
        if (Test-Path -LiteralPath $e) { [void]$c.Add($e) }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $real = & $py.Source -3 -c "import sys;print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $real) { [void]$c.Add(("$real").Trim()) }
    }
    $g = Get-Command python -ErrorAction SilentlyContinue
    if ($g) { [void]$c.Add($g.Source) }          # tested below, not trusted
    return $c
}

function Find-PymupdfDir {
    $dirs = @()
    foreach ($v in @($env:PYMUPDF_PATH, $env:PDF3D_LIBS)) { if ($v) { $dirs += $v } }
    $dirs += (Join-Path $PSScriptRoot '..\libs')
    $dirs += "$env:USERPROFILE\.dsh\skills\pdf-to-black\libs"
    $dirs += (Get-ChildItem "$env:USERPROFILE\.dsh\skills" -Directory -ErrorAction SilentlyContinue |
              ForEach-Object { Join-Path $_.FullName 'libs' })
    $dirs += "$env:USERPROFILE\.workbuddy\libs"
    foreach ($d in $dirs) {
        if (-not $d) { continue }
        if (Test-Path -LiteralPath (Join-Path $d 'pymupdf')) { return (Resolve-Path $d).Path }
        if (Test-Path -LiteralPath (Join-Path $d 'fitz')) { return (Resolve-Path $d).Path }
    }
    return $null
}

function Get-SolidWorksRedist {
    $c = @(
        'C:\sw2025\SOLIDWORKS\api\redist',
        "$env:ProgramFiles\SOLIDWORKS Corp\SOLIDWORKS\api\redist",
        "${env:ProgramFiles(x86)}\SOLIDWORKS Corp\SOLIDWORKS\api\redist"
    )
    foreach ($d in $c) {
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'SolidWorks.Interop.sldworks.dll'))) { return $d }
    }
    return $null
}

function Get-PartTemplate {
    Get-ChildItem 'C:\ProgramData\SOLIDWORKS' -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'templates\gb_part.prtdot' } |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Get-PipelineEnv {
    $S = $PSScriptRoot
    if (-not (Test-Path (Join-Path $S 'drawing_spec.py'))) {
        $S = Join-Path $PSScriptRoot 'scripts'
    }

    $lib = Find-PymupdfDir
    if ($lib) { $env:PYMUPDF_PATH = $lib }

    $PY = $null
    foreach ($cand in (Get-PythonCandidates)) {
        if (Test-PyExe -Exe $cand) { $PY = $cand; break }
    }
    $pymuOk = $false
    if ($PY -and (Test-PyExe -Exe $PY -NeedPymu)) { $pymuOk = $true }

    $acad = Get-Process acad -ErrorAction SilentlyContinue | Select-Object -First 1
    $redist = Get-SolidWorksRedist
    $tpl = Get-PartTemplate

    [pscustomobject]@{
        PY         = $PY
        S          = $S
        PyMuOk     = $pymuOk
        PyMuDir    = $lib
        AcadPid    = if ($acad) { $acad.Id } else { 0 }
        SWRedist   = $redist
        Template   = $tpl
        Ready      = [bool]($PY -and $pymuOk -and $redist)
    }
}
