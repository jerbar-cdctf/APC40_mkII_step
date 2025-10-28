# APC40 MKII STEP SEQUENCER - DEPLOYMENT SCRIPT
# Clears cache, deploys latest files, and launches Ableton Live

# Programmatically find Ableton log location
$abletonPrefsPath = $null
$abletonLogPath = $null

# Search for Live folders in AppData\Roaming\Ableton
$abletonBaseDir = "$env:APPDATA\Ableton"
if (Test-Path $abletonBaseDir) {
    $liveFolders = Get-ChildItem -Path $abletonBaseDir -Directory -Filter "Live 12.*" | Sort-Object Name -Descending
    if ($liveFolders) {
        # Use the first (most recent) Live version found
        $liveFolder = $liveFolders[0]
        $prefsFolder = Join-Path $liveFolder.FullName "Preferences"
        if (Test-Path $prefsFolder) {
            $abletonPrefsPath = $prefsFolder
            $abletonLogPath = Join-Path $prefsFolder "Log.txt"
            Write-Host "Found Ableton preferences: $abletonPrefsPath" -ForegroundColor Cyan
        }
    }
}

# Fallback to default if not found
if (-not $abletonPrefsPath) {
    $abletonPrefsPath = "$env:APPDATA\Ableton\Live 12.2.6\Preferences"
    $abletonLogPath = "$abletonPrefsPath\Log.txt"
    Write-Host "Using default Ableton path: $abletonPrefsPath" -ForegroundColor Yellow
}

# Set debugger log to same folder as Ableton log
$logPath = Join-Path $abletonPrefsPath "Sequencer_Debugger.txt"

Write-Host "Debugger log will be saved to: $logPath" -ForegroundColor Green
Write-Host ""

# Clear both logs
if (Test-Path $abletonLogPath) {
    Clear-Content -Path $abletonLogPath
    Write-Host "Cleared Ableton log" -ForegroundColor Gray
}
if (Test-Path $logPath) {
    Clear-Content -Path $logPath
    Write-Host "Cleared debugger log" -ForegroundColor Gray
}
Write-Host ""

#Lets now flush the APC40 mkII step sequencer files, and install the updated controller files.
$apc40mkii_step_sequencer_path = "C:\Users\$env:USERNAME\GitHub\APC40_mkII_step\APC40_MkII_step"
$LiveControllerPath = "C:\ProgramData\Ableton\Live 12 Lite\Resources\MIDI Remote Scripts\APC40_MkII_step"

# NUCLEAR OPTION: Delete entire APC40_MkII_step folder and recreate
if (Test-Path $LiveControllerPath) {
    Remove-Item -Path $LiveControllerPath -Recurse -Force -ErrorAction SilentlyContinue -confirm:$false
}
New-Item -Path $LiveControllerPath -ItemType Directory -Force | Out-Null

$items=Get-ChildItem -Path "$apc40mkii_step_sequencer_path\*.py"
foreach ($item in $items) {
    Copy-Item -Path $item.FullName -Destination "$LiveControllerPath" -Force -ErrorAction Stop
}

#Launch Live
Start-Process "C:\ProgramData\Ableton\Live 12 Lite\Program\Ableton Live 12 Lite.exe"
Clear-Host
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
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  DEBUG LOG (REAL-TIME)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Wait for Ableton Live to start
Start-Sleep -Seconds 20
# Show log file path and start monitoring
# Monitor log with live updates
# we'll use a loop to monitor Ableton again, and while running update the log file.
$LogFileLineCountOld = $null
$LogFileLineCountOld = (Get-Content -Path $logPath).Count
Get-Content -Path $logPath
$liveRunning = $null
$process = Get-Process -Name "Ableton Live 12 Lite" -ErrorAction SilentlyContinue
if ($process) {
    $liveRunning = $true
    Write-Host "[OK] Ableton Live detected!" -ForegroundColor Green
    Write-Host ""
 
}
while ($liveRunning) {
    $LogFileLineCountNew = (Get-Content -Path $abletonLogPath).Count
    if ($LogFileLineCountNew -gt $LogFileLineCountOld) {
        Get-Content -Path $abletonLogPath -Tail ($LogFileLineCountNew - $LogFileLineCountOld)
    }
    $process = Get-Process -Name "Ableton Live 12 Lite" -ErrorAction SilentlyContinue
    if ($process) {
        $liveRunning = $true
        $LogFileLineCountOld = $LogFileLineCountNew  
    } else {
        $liveRunning = $false
        #Exit without error
    }
}
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
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  DEBUG LOG (REAL-TIME)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
