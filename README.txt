================================================================================
                    APC40 MKII STEP SEQUENCER
                    Advanced MIDI Remote Script
                    For Ableton Live 12+
================================================================================

OVERVIEW
--------
A powerful step sequencer for the AKAI APC40 mkII that transforms your 
controller into a hardware step sequencer with scale awareness, MPE support,
and advanced editing functions. Perfect for live performance, improvisation,
and creative beat-making.


INSTALLATION
------------
1. Copy the APC40_MkII_step folder to:
   C:\ProgramData\Ableton\Live 12\Resources\MIDI Remote Scripts\

2. Open Ableton Live
3. Go to Preferences > Link, Tempo & MIDI
4. Under Control Surface, select "APC40_MkII_step"
5. Set Input/Output to your APC40 mkII
6. Restart Live


ENTERING STEP SEQUENCER MODE
-----------------------------
Press the USER button to enter/exit Step Sequencer mode.

When active:
- Matrix becomes 8x5 step grid (8 steps x 5 notes)
- Clip Stop buttons show playhead position
- Track Select buttons control note length
- Scene Launch buttons control functions per drum/note


GRID LAYOUT (ABLETON-STYLE)
----------------------------
The grid matches Ableton's piano roll exactly:
- TOP ROW = Higher notes
- BOTTOM ROW = Lower notes

Current visible notes are logged when you navigate up/down.


INSTRUMENT TYPES
----------------
The sequencer automatically detects and adapts:

DRUM RACKS:
- Shows only loaded drum pads (with samples)
- Simple GREEN/BLUE coloring
- Navigation scrolls through loaded pads only

MELODIC INSTRUMENTS:
- Full 128-note chromatic range
- Scale-aware color coding (see below)
- Starts at C3 (middle C)
- Navigation scrolls through all notes


SCALE AWARENESS (MELODIC ONLY)
-------------------------------
The sequencer reads Ableton's scale settings and color-codes pads:

EMPTY PADS:
- BLUE (dim) = In-scale notes (safe to use)
- CYAN = Root note (tonic/key center)
- OFF (dark) = Chromatic notes (available but out of scale)

ACTIVE NOTES:
- GREEN = In-scale active notes
- ORANGE = Chromatic active notes (passing tones, tension)
- BLINKING ORANGE = Just became chromatic (after key change)

SELECTED ROW:
- Always BLUE when empty, GREEN when has note

LIVE KEY CHANGES:
The sequencer checks for scale changes at the end of each loop (perfect for
improv sets). Notes that become chromatic will blink ORANGE for ~10 blinks
as a visual alert.


NAVIGATION
----------
LEFT/RIGHT BUTTONS - Navigate through time pages (8 steps per page)
UP/DOWN BUTTONS - Navigate through notes/drums
  UP = Higher notes
  DOWN = Lower notes

DEVICE CONTROL KNOBS:
  Knob 1 (no shift) = Pressure (MPE)
  Knob 1 (with shift) = Velocity
  Knob 2 = Mirrors the other parameter


MATRIX GRID (8x5)
-----------------
Press pads to add/remove notes at that step.

SELECTED ROW COLORS:
- BLUE = Empty step (selected row)
- GREEN = Note present (selected row)

OTHER ROWS:
- See Scale Awareness section above
- Drum racks use simple GREEN/BLUE coloring


PLAYHEAD TRACKING
-----------------
CLIP STOP BUTTONS (Top Row):
- PINK (blinking) = Current playhead on visible grid
- RED (blinking) = Current playhead off visible grid  
- ORANGE (solid) = Loop length indicators

The white playhead bar on the matrix matches Ableton's beat position exactly.


NOTE LENGTH SELECTION
---------------------
TRACK SELECT BUTTONS (Bottom Row, buttons 1-8):
Press to cycle through note lengths:
  1/16 bar → 1/8 bar → 1/4 bar → 1/2 bar → 1 bar → 2 bars → 4 bars → 8 bars

Current selection lights up ORANGE.
When changing, a rainbow animation shows coverage on the grid.


LOOP LENGTH CONTROL
-------------------
MASTER BUTTON + TRACK SELECT:
Hold Master, press Track Select buttons to set loop length:
  Button 1 = 1 bar
  Button 2 = 2 bars
  Button 3 = 4 bars
  Button 4 = 8 bars
  Button 5 = 16 bars


FUNCTION SYSTEM
---------------
The function system allows batch operations on multiple drums/notes.

STOP ALL CLIPS BUTTON:
Cycles through available functions. Watch scene launch buttons blink to 
preview the selected function color.

SCENE LAUNCH BUTTONS (Right Side, 5 buttons):
Toggle function assignment for each row (drum/note).
- Press once = Assign function to that row (LED lights in function color)
- Press again = Remove function (LED turns off)

Can assign the same function to multiple rows simultaneously.

MASTER BUTTON:
Executes the selected function on all assigned rows, then clears assignments.

SUCCESS/FAILURE FEEDBACK:
- Success: Master button blinks 3 times (green)
- Failure: Master button blinks 5 times (red)


FUNCTION COLORS & ACTIONS
--------------------------
RED = Clear all notes from selected drums/notes
YELLOW = Copy notes from selected drums (read-only)
ORANGE = Paste copied notes to selected drums
BLUE = MPE Marker (visual only, no action yet - reserved for MPE features)
PURPLE = Fill with quarter notes (1 beat intervals)
DARK PURPLE = Fill with eighth notes (0.5 beat intervals)
LIME GREEN = Fill with sixteenth notes (0.25 beat intervals)
GREEN = Fill with whole notes (4 beat intervals)


FUNCTION WORKFLOW EXAMPLE
--------------------------
1. Press STOP ALL CLIPS → Cycles to YELLOW (Copy)
2. Press Scene buttons for rows 1 and 3 → Both show YELLOW
3. Press MASTER → Copies notes from rows 1 and 3 to buffer
4. Press STOP ALL CLIPS → Cycles to ORANGE (Paste)
5. Press Scene button for row 5 → Shows ORANGE
6. Press MASTER → Pastes copied notes to row 5
7. All assignments cleared automatically


MPE SUPPORT
-----------
The sequencer supports MPE (MIDI Polyphonic Expression):

DEVICE CONTROL KNOBS:
- Knob 1 (no shift) = Pressure (MPE Channel Pressure)
- Knob 1 (shift held) = Velocity

ASSIGNABLE KNOBS (8 knobs above matrix):
- No shift = Pitch Bend (per-note MPE)
- Shift held = Slide (CC74, MPE Y-axis)

Values are stored per-drum/note and applied to new notes automatically.


PERFORMANCE OPTIMIZATIONS
--------------------------
- Clip reference caching (80% reduction in clip lookups)
- Live 12 API used throughout
- Dynamic buffer sizing (only allocates what's needed)
- Smart LED updates (only on changes)
- 90ms tick rate for smooth tracking
- Zero overhead scale detection (O(1) lookups)


LOGGING
-------
The script logs important events to Ableton's Log.txt:
  %AppData%\Ableton\Live 12.x.x\Preferences\Log.txt

Useful for debugging and understanding what the sequencer is doing.


TIPS & TRICKS
-------------
1. LEARN SCALES: Watch the color patterns to visualize scales on the grid
2. ROOT FINDER: Look for CYAN pads to instantly find root notes
3. JAZZ IMPROV: See chord tones (BLUE) vs passing tones (OFF)
4. KEY CHANGES: Watch for blinking ORANGE notes after modulation
5. BATCH EDIT: Use functions to quickly copy patterns between drums
6. DRUM MAPPING: Up/Down navigation shows only loaded pads
7. LOOP SYNC: Playhead tracking works at any tempo (tested up to 180 BPM)


SUPPORTED SCALES (28 TOTAL)
----------------------------
Major, Minor, Dorian, Mixolydian, Lydian, Phrygian, Locrian, Diminished,
Whole Tone, Whole-Half, Half-Whole, Harmonic Minor, Melodic Minor, 
Super Locrian, Bhairav, Hungarian Minor, Minor Blues, Major Blues,
Minor Pentatonic, Major Pentatonic, Spanish, Gypsy, Arabian, Flamenco,
Japanese, Egyptian, Blues, Chromatic


REQUIREMENTS
------------
- AKAI APC40 mkII controller
- Ableton Live 12+ (uses Live 12 API)
- Windows (tested) or macOS (should work)


TROUBLESHOOTING
---------------
If notes aren't placing:
1. Make sure you have a MIDI clip in the selected track/scene
2. Check that clip detail view is visible in Ableton
3. Try exiting and re-entering sequencer mode (USER button)

If colors seem wrong:
1. Check Ableton's scale setting (Track > Set Scale)
2. Drum racks don't use scale colors (by design)

If navigation feels weird:
1. Check log to see visible note range
2. Remember: TOP row = higher notes, BOTTOM row = lower notes


CHANGELOG
---------
v1.0 - Initial release
  - 8x5 step grid with Ableton-style layout
  - Smart drum pad detection
  - Scale-aware visual guidance (melodic only)
  - Live key change detection
  - Function system (copy/paste/fill/clear)
  - MPE support
  - Performance optimizations
  - Full 128-note chromatic range support


CREDITS
-------
Created by Jeremy
Developed for Ableton Live 12 with Python 3.11
Tested with AKAI APC40 mkII


LICENSE
-------
This MIDI Remote Script is provided as-is for use with Ableton Live.
Feel free to modify and share, but please give credit.


CONTACT & SUPPORT
-----------------
For bugs, feature requests, or questions, check the log file first:
  %AppData%\Ableton\Live 12.x.x\Preferences\Log.txt

Many questions can be answered by reading the logged output when using
the sequencer.


================================================================================
                    ENJOY CREATING MUSIC!
================================================================================
