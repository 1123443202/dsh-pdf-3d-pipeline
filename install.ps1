# install.ps1 - expose this pipeline to other agents.
#
#   1) as a skill folder (junction, one source of truth):
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -List
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Targets dsh,workbuddy
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Targets claude -Copy
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Remove -Targets claude
#
#   2) as a dsh bundle (registered in the dsh profile, loaded at startup):
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Register
#        powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Unregister
#
# ASCII only on purpose: PowerShell 5.1 reads BOM-less scripts as ANSI, so any
# Chinese text in here would arrive mangled. The docs are UTF-8, this file is not.
param(
    [string[]]$Targets,
    [switch]$Copy,
    [switch]$Remove,
    [switch]$List,
    [switch]$Register,
    [switch]$Unregister,
    [string]$Profile = 'desktop'
)

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$name = Split-Path -Leaf $src
$pkgName = 'dsh-pdf-3d-pipeline'

$map = [ordered]@{
    'dsh'       = "$env:USERPROFILE\.dsh\skills"
    'workbuddy' = "$env:USERPROFILE\.workbuddy\skills"
    'claude'    = "$env:USERPROFILE\.claude\skills"
    'codex'     = "$env:USERPROFILE\.codex\skills"
    'cursor'    = "$env:USERPROFILE\.cursor\skills"
    'agents'    = "$env:USERPROFILE\.agents\skills"
}

function Show-All {
    Write-Output ("source : {0}" -f $src)
    Write-Output ("name   : {0}" -f $name)
    Write-Output ''
    foreach ($k in $map.Keys) {
        $parent = $map[$k]
        $link = Join-Path $parent $name
        $state = 'parent missing'
        if (Test-Path -LiteralPath $parent) {
            if (Test-Path -LiteralPath $link) {
                $it = Get-Item -LiteralPath $link -Force
                $state = if ($it.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { 'linked' } else { 'real dir' }
            } else { $state = 'not installed' }
        }
        Write-Output ("  {0,-11} {1,-16} {2}" -f $k, $state, $parent)
    }
    Show-Registry
}

# ---------- dsh profile registration ----------

function ProfilePaths {
    $dir = Join-Path $env:USERPROFILE ".dsh\profiles\$Profile"
    [pscustomobject]@{
        Dir = $dir
        Pkg = Join-Path $dir 'package.json'
        Mod = Join-Path $dir "node_modules\$pkgName"
    }
}

function Show-Registry {
    $p = ProfilePaths
    Write-Output ''
    if (-not (Test-Path -LiteralPath $p.Pkg)) { Write-Output ("dsh profile: {0} not found" -f $p.Dir); return }
    $raw = Get-Content -LiteralPath $p.Pkg -Raw
    $dep = $raw -match [regex]::Escape('"' + $pkgName + '"')
    $mod = Test-Path -LiteralPath $p.Mod
    Write-Output ("dsh profile: {0}" -f $p.Dir)
    Write-Output ("  {0,-14} {1}" -f 'in package.json', $(if ($dep) { 'yes' } else { 'no' }))
    Write-Output ("  {0,-14} {1}" -f 'in node_modules', $(if ($mod) { 'yes' } else { 'no' }))
}

function Write-Utf8NoBom([string]$path, [string]$text) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $text, $enc)
}

function Add-Dependency([string]$raw) {
    # Insert right after the opening brace of "dependencies", keeping the file's
    # own indentation and key order instead of re-serialising it.
    $depValue = 'file:' + ($src -replace '\\', '/')
    $anchor = '"dependencies": {'
    $idx = $raw.IndexOf($anchor)
    if ($idx -lt 0) { throw 'package.json has no "dependencies" block' }
    $at = $idx + $anchor.Length
    $nl = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
    $indent = '    '
    $line = $nl + $indent + '"' + $pkgName + '": "' + $depValue + '",'
    return $raw.Insert($at, $line)
}

function Add-Bundle([string]$raw) {
    $anchor = '"bundles": ['
    $idx = $raw.IndexOf($anchor)
    if ($idx -lt 0) { throw 'package.json has no dsh.profile.bundles array' }
    $at = $idx + $anchor.Length
    $nl = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
    $line = $nl + '        "' + $pkgName + '",'
    return $raw.Insert($at, $line)
}

function Register-Bundle {
    $p = ProfilePaths
    if (-not (Test-Path -LiteralPath $p.Pkg)) { throw "dsh profile not found: $($p.Dir)" }

    $raw = Get-Content -LiteralPath $p.Pkg -Raw
    if ($raw -match [regex]::Escape('"' + $pkgName + '"')) {
        Write-Output "already registered in $($p.Pkg)"
    } else {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item -LiteralPath $p.Pkg -Destination "$($p.Pkg).bak-$stamp" -Force
        Write-Output "backup -> $($p.Pkg).bak-$stamp"

        if ($raw -notmatch '"dependencies"\s*:\s*\{') { throw 'unexpected package.json shape (dependencies)' }
        $new = Add-Dependency $raw
        $new = Add-Bundle $new
        # validate before writing: a broken profile package.json means dsh will
        # not start, and the user finds out the hard way.
        try { $null = $new | ConvertFrom-Json } catch { throw "edit produced invalid JSON, nothing written: $($_.Exception.Message)" }
        Write-Utf8NoBom $p.Pkg $new
        Write-Output "registered bundle $pkgName"
    }

    if (Test-Path -LiteralPath $p.Mod) {
        Write-Output "node_modules link already present"
    } else {
        $null = New-Item -ItemType Junction -Path $p.Mod -Target $src
        Write-Output "linked node_modules\$pkgName -> $src"
    }
    Write-Output ''
    Write-Output 'Restart dsh completely (quit from the tray, not just the window) to load the bundle.'
}

function Unregister-Bundle {
    $p = ProfilePaths
    if (Test-Path -LiteralPath $p.Mod) {
        [void](cmd /c rmdir "`"$($p.Mod)`"")
        Write-Output "removed node_modules\$pkgName"
    }
    if (-not (Test-Path -LiteralPath $p.Pkg)) { return }
    $raw = Get-Content -LiteralPath $p.Pkg -Raw
    if ($raw -notmatch [regex]::Escape('"' + $pkgName + '"')) { Write-Output 'not registered'; return }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item -LiteralPath $p.Pkg -Destination "$($p.Pkg).bak-$stamp" -Force
    $esc = [regex]::Escape($pkgName)
    # Drop the whole line (including its newline) for both the dependency entry
    # and the bundles entry, so the file comes back byte-identical minus our two
    # lines instead of accumulating blank ones on every round trip.
    $new = [regex]::Replace($raw, "(?m)^[ \t]*`"$esc`"[ \t]*:[^\r\n]*\r?\n", "")
    $new = [regex]::Replace($new, "(?m)^[ \t]*`"$esc`"[ \t]*,?[ \t]*\r?\n", "")
    # A comma left dangling before ] or } is the one thing that turns this edit
    # into an unstartable dsh.
    $new = [regex]::Replace($new, ",(\s*[\]\}])", '$1')
    try { $null = $new | ConvertFrom-Json } catch { throw "edit produced invalid JSON, nothing written: $($_.Exception.Message)" }
    Write-Utf8NoBom $p.Pkg $new
    Write-Output "unregistered $pkgName (backup $($p.Pkg).bak-$stamp)"
}

if ($Register) { Register-Bundle; Show-All; return }
if ($Unregister) { Unregister-Bundle; Show-All; return }

# ---------- skill folder links ----------

if ($List -or -not $Targets) { Show-All; if (-not $Targets) { return } }

foreach ($t in $Targets) {
    if (-not $map.Contains($t)) { Write-Output "skip $t : unknown target"; continue }
    $parent = $map[$t]
    if (-not (Test-Path -LiteralPath $parent)) {
        Write-Output "skip $t : $parent does not exist (that agent is not installed here)"
        continue
    }
    $link = Join-Path $parent $name

    if ($Remove) {
        if (Test-Path -LiteralPath $link) {
            $it = Get-Item -LiteralPath $link -Force
            if ($it.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                [void](cmd /c rmdir "`"$link`"")
                Write-Output "removed link $link"
            } else {
                Write-Output "skip $t : $link is a real directory, delete it yourself"
            }
        } else { Write-Output "skip $t : not installed" }
        continue
    }

    if (Test-Path -LiteralPath $link) {
        Write-Output "skip $t : already present at $link"
        continue
    }
    if ($Copy) {
        Copy-Item -LiteralPath $src -Destination $link -Recurse -Force
        Write-Output "copied  -> $link"
    } else {
        $null = New-Item -ItemType Junction -Path $link -Target $src
        Write-Output "linked  -> $link"
    }
}

Write-Output ''
Show-All
