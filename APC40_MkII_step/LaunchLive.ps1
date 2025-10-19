# APC40 MKII STEP SEQUENCER - DEPLOYMENT SCRIPT
# Clears cache, deploys latest files, and launches Ableton Live

#Lets clear the Ableton Log at %appdata%\Ableton\Live <version>\Preferences\Log.txt
Clear-Content -Path "$env:APPDATA\Ableton\Live 12.2.5\Preferences\Log.txt"

#Lets now flush the APC40 mkII step sequencer files, and install the updated controller files.
$apc40mkii_step_sequencer_path = "C:\Users\$env:USERNAME\GitHub\APC40_mkII_step\APC40_MkII_step"
$LiveControllerPath = "C:\ProgramData\Ableton\Live 12 Lite\Resources\MIDI Remote Scripts\APC40_MkII_step"
$pychace=$LiveControllerPath + "\__pycache__"
$pycacheFiles=Get-ChildItem -Path "$pychace" -Force
foreach ($item in $pycacheFiles) {
    Remove-Item -Path $item.FullName -Force -ErrorAction SilentlyContinue -confirm:$false
}
$RemoveItems=Get-ChildItem -Path "$LiveControllerPath" -Force
foreach ($item in $RemoveItems) {
    Remove-Item -Path $item.FullName -Force -ErrorAction SilentlyContinue -confirm:$false
}

$items=Get-ChildItem -Path "$apc40mkii_step_sequencer_path\*.py"
foreach ($item in $items) {
    Copy-Item -Path $item.FullName -Destination "$LiveControllerPath" -Force -ErrorAction Stop
}

#Launch Live
Start-Process "C:\ProgramData\Ableton\Live 12 Lite\Program\Ableton Live 12 Lite.exe"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  APC40 MKII STEP SEQUENCER LAUNCHED" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "FUNCTION COLORS & ACTIONS" -ForegroundColor White
Write-Host "-------------------------" -ForegroundColor White
Write-Host "RED = Clear notes" -ForegroundColor Red
Write-Host "YELLOW = Copy notes" -ForegroundColor Yellow
Write-Host "ORANGE = Paste notes" -ForegroundColor DarkYellow
Write-Host "BLUE = MPE Marker (visual indicator)" -ForegroundColor Blue 
Write-Host "PURPLE = Fill with quarter notes" -ForegroundColor Magenta
Write-Host "DARK PURPLE = Fill with eighth notes" -ForegroundColor DarkMagenta
Write-Host "LIME Green = Fill with sixteenth notes" -ForegroundColor Green
Write-Host "GREEN = Fill with whole notes" -ForegroundColor DarkGreen

Write-Host ""
Write-Host "SCALE COLORS (Melodic Only)" -ForegroundColor White
Write-Host "----------------------------" -ForegroundColor White
Write-Host "BLUE (dim) = In-scale notes available" -ForegroundColor Blue
Write-Host "CYAN = Root note (tonic)" -ForegroundColor Cyan
Write-Host "OFF (dark) = Chromatic notes available" -ForegroundColor DarkGray
Write-Host "GREEN = Active in-scale notes" -ForegroundColor Green
Write-Host "ORANGE = Active chromatic notes" -ForegroundColor DarkYellow
Write-Host "BLINKING ORANGE = Just became chromatic (key change)" -ForegroundColor Yellow

Write-Host ""
Write-Host "NOTE: Drum racks use simple GREEN/BLUE coloring (no scale colors)" -ForegroundColor Gray
Write-Host "      Scale detection checks for key changes at end of each loop" -ForegroundColor Gray
Write-Host ""
Write-Host "Press USER button to enter Step Sequencer mode" -ForegroundColor White
Write-Host "Check README.txt for full documentation" -ForegroundColor White
Write-Host "" 