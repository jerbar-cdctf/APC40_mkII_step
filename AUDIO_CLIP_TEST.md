# Audio Clip Mode - Detailed Test Plan

## Current Status
✅ **Audio clip detection**: Working ("Audio clip mode active" in log)
✅ **Instrument mode note length**: FIXED! Now working correctly
❌ **Audio clip UI**: Not showing expected interface

## What SHOULD Happen in Audio Clip Mode

### When You Load Audio Clip (AIF/WAV) and Press USER:

#### Track Select Button LEDs Should:
- **Button with GREEN LED** = Current view mode (default: button 0)
- **Buttons with BLUE LED** = Available view modes (buttons 1-7)
- **All 8 buttons should light up** when entering audio mode

#### 8x5 Grid Should Show:
- **Row 0 (top)**: Loop START markers (GREEN at beat 0)
- **Row 1**: Left channel waveform (GREEN = medium intensity)
- **Row 2**: Warp marker positions (ORANGE if markers exist)
- **Row 3**: Right channel waveform (GREEN = medium intensity)
- **Row 4 (bottom)**: Loop END markers (RED at end beat)

### When You Press Track Select Buttons:
- Should see log: `[AUDIO_SAMPLE] Audio view mode request: index=X`
- Should see log: `[AUDIO_SAMPLE] Audio view mode set to X`
- Track select LEDs should update (new GREEN, others BLUE)
- Grid should refresh with new zoom level

## Specific Test Steps

### Test 1: Enter Audio Mode
1. **Load an audio file** (AIF, WAV, MP3, etc.)
2. **Press USER button**
3. **Look at Sequencer_Debugger.txt** - should see:
   ```
   [GENERAL] Audio clip mode active
   [GENERAL] Loop: 0.0 to X.X beats
   ```
4. **Look at track select buttons** (row of 8 buttons)
   - **Question**: Do ANY of them light up?
   - **Question**: What colors do you see?

### Test 2: Press Track Select Buttons
1. **While in audio mode, press track select button 1**
2. **Check log** - should see:
   ```
   [BUTTON_PRESS] Track select pressed: index=1 shift=False sequencer=ClipSequencer
   [AUDIO_SAMPLE] Audio view mode request: index=1
   [AUDIO_SAMPLE] Audio view mode set to 1
   ```
3. **Look at track select buttons**
   - **Question**: Did button 1 turn GREEN?
   - **Question**: Are other buttons BLUE?

### Test 3: Check Grid Display
1. **While in audio mode, look at 8x5 grid**
2. **What colors do you see?**
   - Top row (row 0)?
   - Middle rows?
   - Bottom row (row 4)?
3. **Take a screenshot if possible**

## Known Limitations (Current Implementation)

### Waveform Visualization:
The current implementation shows **placeholder intensity (0.5 = GREEN)** because:
- Real waveform analysis is complex
- Would need to analyze actual audio buffer data
- Currently just shows GREEN for all non-zero audio

### Expected Colors (Current):
- **Row 0**: GREEN at loop start position (column 0 usually)
- **Rows 1-3**: All GREEN (placeholder waveform)
- **Row 4**: RED at loop end position (column 7 usually for 8-beat loop)

## If Track Select Buttons Don't Light Up

**Possible causes:**
1. `render_view_leds()` not being called → Check log for entry messages
2. Buttons not responding to `send_value()` → Hardware issue?
3. Wrong LED color values → Blue might be OFF on your controller?

## If Grid Shows Nothing

**Possible causes:**
1. `refresh_grid()` not being called
2. `_audio_clip_info` not populated correctly
3. LED color constants wrong
4. Grid clearing but not rendering

## What to Report Back

Please test and tell me:
1. ✅ or ❌ **Do track select buttons light up when entering audio mode?**
2. ✅ or ❌ **Do track select buttons change when pressed?**
3. ✅ or ❌ **Do you see AUDIO_SAMPLE logs when pressing buttons?**
4. **What colors do you see on the 8x5 grid?** (describe each row if possible)
5. **Does grid change when you press track select buttons?**
