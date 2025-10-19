# Blink Fix and Enhanced Logging

## Issues Fixed

### 1. Double-Blink / Sync Issue
**Problem**: The beat indicator was blinking twice on the same column, causing it to get out of sync with Ableton.

**Root Cause**: The `_update_blink` method was toggling the blink state (`self._blink_on = not self._blink_on`) on every tick (~60ms), even when the playhead remained in the same column. This caused rapid on/off flickering.

**Fix**: 
- Changed logic to only flash when **entering a new column**
- Added `_blink_phase` counter to create a slower, more visible blink pattern within the same column
- Blink now cycles through phases: flash on (0), hold, flash off (3), hold, repeat
- This ensures sync with Ableton's playhead and creates a cleaner visual indicator

### 2. Note Length Switching Issue
**Problem**: After switching between note lengths several times, the sequencer stops adjusting for the note size.

**Investigation**: Added comprehensive logging to track:
- When note length buttons are pressed
- Old vs new note length values
- Grid refresh after note length change
- Note search parameters during grid refresh
- Note addition/removal with current note length

## Enhanced Logging

### Startup Logging
When entering sequencer mode:
```
=== Sequencer Enter ===
time_page: 0 drum_row_base: 0
note_length_index: 0 loop_bars_index: 0
```

### Note Length Change Logging
When track select button is pressed:
```
=== NOTE LENGTH CHANGE ===
Track button 4 pressed
Old: index=0 length=2.00 beats
New: index=4 length=4.00 beats
Mode active: True
Refreshing grid after note length change...
Grid refresh completed
```

### Grid Refresh Logging
When grid is refreshed:
```
=== GRID REFRESH START ===
Note length: 4.00 beats (index 4)
Time page: 0, Drum base: 0
Loop: 1 bars = 4.0 beats
Grid refresh - found clip
Sample search: col=0 row=0 pitch=36 start=0.000 dur=4.002
  Found 1 notes
Grid refresh complete - found 12 notes to display
```

### Matrix Button Press Logging
When a pad is pressed to add/remove notes:
```
=== MATRIX BUTTON PRESSED ===
Position: col=2 row=1
Pitch: 37, Step: 2
Note length: 4.00 beats (index 4)
Start: 8.000, Search: 7.999-12.001
Found: 0 notes
Note added - pitch: 37 time: 8.0 duration: 4.0 velocity: 64 mpe: 0
```

### Playhead Blink Logging
Periodic playhead position tracking (every 8 steps):
```
Playhead: pos=0.123 step=0 col=0 note_len=4.00
Playhead: pos=32.456 step=8 col=0 note_len=4.00
```

## Changes Made

### StepSequencer.py

#### Added Instance Variables
- `_blink_phase`: Tracks the current phase of the blink cycle (0-5)

#### Modified Methods

**`_update_blink()`**:
- Restructured to only update LEDs when column changes
- Added phase-based blinking for smoother animation
- Added playhead position logging
- Added error logging for blink calculations

**`_on_track_select()`**:
- Added detailed logging for old/new note length values
- Added explicit grid refresh call after note length change
- Added error logging for grid refresh failures

**`_refresh_grid()`**:
- Added header logging with current sequencer state
- Added sample logging for first column note searches
- Added found notes count logging

**`_on_matrix_button()`**:
- Enhanced logging with detailed position and note length info
- Shows search parameters and results
- Logs both note additions and removals

## Testing Instructions

1. **Load Ableton and activate the script**
2. **Open the log file**: `C:\Users\Jeremy\AppData\Roaming\Ableton\Live 12.2.5\Preferences\Log.txt`
3. **Enter sequencer mode** (press User button)
4. **Test blink sync**:
   - Start playback
   - Watch the beat indicator - should flash red/yellow once per column change
   - Should stay in sync with Ableton's playhead
5. **Test note length switching**:
   - Add some notes at one note length (e.g., 1 bar)
   - Switch to a different note length (e.g., 1/4 bar)
   - Check log for "NOTE LENGTH CHANGE" and "GRID REFRESH" messages
   - Verify grid shows notes correctly at new step size
   - Add/remove notes and check they use the correct length
6. **Look for issues in log**:
   - Search for "error:" to find any errors
   - Check if note length values are updating correctly
   - Verify search parameters match current note length

## What to Watch For

### Blink Issues
If blink is still out of sync, the log will show:
- `Playhead:` messages with position info
- Compare `pos` value to what you see in Ableton's transport

### Note Length Issues
If note length stops working, look for:
- Are "NOTE LENGTH CHANGE" messages appearing when you press buttons?
- Is `note_length_index` getting updated correctly?
- Do "GRID REFRESH" messages show the new length?
- When adding notes, does the "Note added" message show the correct duration?

## Next Steps

If issues persist after these fixes:
1. Share relevant log excerpts showing the problem
2. Note which specific action sequence causes the issue
3. Check if the issue happens with specific note lengths (e.g., only with 8 bars)
4. Test if clearing/reopening the clip helps
