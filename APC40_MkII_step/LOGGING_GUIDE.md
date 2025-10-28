# Step Sequencer Logging System Guide

## Overview
The step sequencer uses a **granular logging system** that writes to a separate file (`Sequencer_Debugger.txt`) with category-based filtering.

## Architecture Update (Modular Components)
The sequencer has been refactored into modular components for better performance and maintainability:

- **SequencerBase.py** - Shared functionality (LED management, clip access, logging helpers)
- **DrumSequencer.py** - Drum-specific operations (drum rack detection, function system)
- **InstrumentSequencer.py** - Melodic instrument operations (scale detection, chromatic notes)
- **ClipSequencer.py** - Audio clip operations (waveform visualization, warp controls)
- **StepSequencer.py** - Main coordinator (detects clip type, delegates to appropriate component)
- **SequencerLogger.py** - Centralized logging system

## Log File Location
**Default:** `%TEMP%\Sequencer_Debugger.txt`  
**Typical Path:** `C:\Users\<YourName>\AppData\Local\Temp\Sequencer_Debugger.txt`

You can monitor this file in real-time with PowerShell:
```powershell
Get-Content $env:TEMP\Sequencer_Debugger.txt -Wait
```

## Logging Categories

Each logging call is categorized, allowing you to enable/disable specific areas:

| Category                    | Default | Description                                              |
|:----------------------------|:-------:|:---------------------------------------------------------|
| **GENERAL**                 |   OFF   | General/uncategorized messages                           |
| **INSTRUMENT_DETECTION**    |   ON    | Device detection and classification (drums vs melodic)   |
| **AUDIO_SAMPLE**            |   ON    | Audio clip detection and sample manipulation             |
| **GRID_REFRESH**            |   ON    | Grid rendering and note display                          |
| **NOTE_OPERATIONS**         |   ON    | Add/remove/modify notes                                  |
| **NAVIGATION**              |   OFF   | Up/Down/Left/Right movements                             |
| **CLIP_OPERATIONS**         |   OFF   | Clip slot access and manipulation                        |
| **SCALE_DETECTION**         |   OFF   | Scale/key detection and changes                          |
| **BUTTON_PRESS**            |   ON    | Raw button press events (includes audio loop editing)    |
| **TIMING**                  |   OFF   | Tempo, ticks, playhead updates                           |
| **FUNCTIONS**               |   OFF   | Copy/paste/clear/fill functions                          |
| **ENTRY_EXIT**              |   ON    | Sequencer mode enter/exit                                |
| **ERRORS**                  |   ON    | All errors and exceptions (always logged)                |
| **PERFORMANCE**             |   OFF   | Performance metrics                                      |
|:----------------------------|:-------:|:---------------------------------------------------------|

## Configuring Categories

### Edit in Code (SequencerLogger.py)

Open `SequencerLogger.py` and modify the `CATEGORIES` dictionary:

```python
CATEGORIES = {
    'INSTRUMENT_DETECTION': True,   # Enable
    'GRID_REFRESH': False,          # Disable
    'NOTE_OPERATIONS': True,        # Enable
    # ... etc
}
```

### Enable/Disable at Runtime (Advanced)

You can add Python code to toggle categories programmatically:

```python
# In StepSequencer.py __init__ or _enter method:
_logger.enable_category('GRID_REFRESH')
_logger.disable_category('INSTRUMENT_DETECTION')
_logger.enable_all()  # Enable everything
_logger.disable_all() # Disable all except ERRORS
```

## Adding New Logging Calls

When adding logging to your code, use the appropriate category:

```python
# Instrument detection
self._log("Detected Wavetable synth", 'INSTRUMENT_DETECTION')

# Note operations
self._log("Added note at pitch %d" % pitch, 'NOTE_OPERATIONS')

# Navigation
self._log("Moved up to row %d" % row, 'NAVIGATION')

# Errors
self._log("Failed to access clip: %s" % str(e), 'ERRORS')

# Backward compatible (uses 'GENERAL' category)
self._log("Some message")  # No category = GENERAL
```

## Common Debugging Scenarios

### Debug Instrument Detection Issues
```python
# In SequencerLogger.py:
'INSTRUMENT_DETECTION': True,
'ENTRY_EXIT': True,
'ERRORS': True,
```

**Watch for:**
- Device detection messages
- Sampler/Simpler/Drum Rack classification
- Instrument Rack chain inspection

### Debug Note Display/Editing Issues
```python
'GRID_REFRESH': True,
'NOTE_OPERATIONS': True,
'CLIP_OPERATIONS': True,

# Enable rhythmic LED diagnostics
'NOTE_LENGTH': True,
'TIMING': True,
```

**Watch for:**
- Note count in refresh
- Add/remove operations
- Clip access errors
- **New:** `NOTE_LENGTH` now logs when 1/32 and 1/64 steps are selected (Shift+1/4, Shift+1/8)
- **New:** `TIMING` logs "Grid blink advanced" each tick so you can confirm subdivision blink scheduling

### Debug Navigation Issues
```python
'NAVIGATION': True,
'TIMING': True,
```

**Watch for:**
- Base note changes
- Page navigation
- Playhead updates

### Minimal Logging (Production)
```python
'ERRORS': True,  # Only log errors
# All others: False
```

## LED Color Reference

- Straight note lengths follow the palette documented in `SequencerBase._base_note_length_colors`.
- Triplet/septuplet modes log via `NOTE_LENGTH` when toggled and blink phases via `TIMING`.
- Drum grid refresh entries (`GRID_REFRESH`) now summarize rendered cells and any registered blink patterns.

## Log File Management

### Clear Log File
The log file is cleared and reinitialized each time you launch Live via `LaunchLive.ps1` (since the `SequencerLogger` is instantiated fresh).

### Manual Clear
You can add this to your code:
```python
_logger.clear_log()
```

### View Log Path
```python
# Logs the path to Ableton log
self._log("Debug log: %s" % _logger.get_log_path(), 'ENTRY_EXIT')
```

## Log Format

Each log entry includes:
- **Timestamp** (HH:MM:SS.mmm)
- **Category** tag
- **Message**

Example:
```
[11:57:31.538] [INSTRUMENT_DETECTION] Checking device: name='Emergency Kit', class='InstrumentGroupDevice'
[11:57:31.539] [INSTRUMENT_DETECTION] Found Instrument Rack - checking chains for drum instruments...
[11:57:31.539] [INSTRUMENT_DETECTION]   Chain device: name='Emergency Kit', class='DrumGroupDevice'
[11:57:31.539] [INSTRUMENT_DETECTION] Detected: Drum Rack inside Instrument Rack
```

## Best Practices

1. **Keep ERRORS always ON** - Critical for debugging crashes
2. **Turn OFF verbose categories in production** - Reduces log file size
3. **Enable categories as needed** - Don't enable everything at once
4. **Use separators** for major operations:
   ```python
   _logger.separator("STARTING COPY OPERATION")
   ```
5. **Test category combinations** - Some issues require multiple categories

## Troubleshooting

**Q: No log file created?**  
A: Check that `ENABLE_LOGGING = True` in `StepSequencer.py` (line 6)

**Q: Category not logging?**  
A: Check that the category is set to `True` in `SequencerLogger.py` CATEGORIES dict

**Q: Log file too large?**  
A: Disable verbose categories like GRID_REFRESH, TIMING, BUTTON_PRESS

**Q: Want to log to a different location?**  
A: Modify line 9 in StepSequencer.py:
```python
_logger = SequencerLogger(log_file_path='C:\\MyLogs\\Sequencer.txt')
```

## Fallback Behavior

- If the logger fails, messages fallback to Ableton's `Log.txt`
- **ERRORS** category always writes to both files for safety
- If file I/O fails, logs continue to Ableton log only
