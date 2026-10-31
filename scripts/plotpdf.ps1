# Plot an existing DWG to PDF (standalone, reliable).
#   powershell -NoProfile -STA -ExecutionPolicy Bypass -File plotpdf.ps1 -Dwg x.dwg -Pdf x.pdf
param(
    [Parameter(Mandatory = $true)][string]$Dwg,
    [Parameter(Mandatory = $true)][string]$Pdf
)
$ErrorActionPreference = "Continue"
$log = [System.IO.Path]::ChangeExtension($Pdf, ".plotlog.txt")
function L($m) { Add-Content -Path $log -Value $m -Encoding UTF8 }
"plot start" | Set-Content -Path $log -Encoding UTF8

$acad = New-Object -ComObject AutoCAD.Application.25
try { $acad.Visible = $false } catch { }
Start-Sleep -Milliseconds 400
$doc = $acad.Documents.Open($Dwg)
L "opened $($doc.Name)"

try { $doc.SetVariable("BACKGROUNDPLOT", 0); L "bgplot=0" } catch { L "bgplot FAIL" }
$layout = $doc.ActiveLayout
try { $layout.ConfigName = "DWG To PDF.pc3"; L "config=$($layout.ConfigName)" } catch { L "config FAIL: $($_.Exception.Message)" }
try { $layout.CanonicalMediaName = "ISO_A2_(594.00_x_420.00_MM)"; L "media=$($layout.CanonicalMediaName)" } catch { L "media FAIL: $($_.Exception.Message)" }
try { $layout.PlotType = 1 } catch { }
try { $layout.CenterPlot = $true } catch { }
try { $layout.PlotRotation = 0 } catch { }
try { $layout.UseStandardScale = $true; $layout.StandardScale = 0; L "scale=fit" } catch { L "scale FAIL" }
try { $layout.PlotWithPlotStyles = $true } catch { }
try { $layout.PlotWithLineweights = $true } catch { }

if (Test-Path $Pdf) { Remove-Item $Pdf -Force -ErrorAction SilentlyContinue }
L ("pre-exists=" + (Test-Path $Pdf))

try {
    $r = $doc.Plot.PlotToFile($Pdf)
    L ("PlotToFile returned [" + $r + "]")
} catch { L "PlotToFile FAIL: $($_.Exception.Message)" }

Start-Sleep -Milliseconds 2500
$fi = [System.IO.FileInfo]$Pdf
L ("pdf exists=" + $fi.Exists + " size=" + $(if ($fi.Exists) { $fi.Length } else { 0 }) + " time=" + $(if ($fi.Exists) { $fi.LastWriteTime.ToString("HH:mm:ss") } else { "-" }))

try { $acad.Quit() } catch { }
L "done"
