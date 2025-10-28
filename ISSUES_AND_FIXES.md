# Current Issues and Status

## Issues Reported (Oct 27, 2025 - 10:03 PM)

### 1. Instrument Mode Note Selection Not Working
**Status**: Needs investigation
**Symptom**: Track select buttons not changing note length in instrument mode
**Expected**: Buttons should change note length and update LEDs (like drum mode)

### 2. No Chromatic LED Display in Instrument Mode
**Status**: Fixed in code, but deployment may have failed
**Symptom**: Not seeing scale-aware colors (BLUE/CYAN/ORANGE)
**Expected Color Scheme**:
- **BLUE (dim)**: Available in-scale notes (empty)
- **CYAN**: Root note (empty)
- **OFF**: Chromatic notes available (empty)
- **GREEN**: Active notes (in-scale)
- **ORANGE**: Active chromatic notes (out of scale)

**Current Symptom**: "top grid led column 1 is green, next row is all green, next row is off"

### 3. Clip Mode Not Working (Audio Clips)
**Status**: Needs implementation check
**Symptom**: Cannot adjust anything in clip mode
**Expected**: 
- Track select buttons should control view/zoom
- Grid should show audio waveform visualization
- Controls should allow warp marker placement, gain adjustment, etc.

**Current Symptom**: Showing green colors instead of clip mode interface

## Recent Code Changes

### Files Modified:
1. **DrumSequencer.py**
   - Fixed `ctr` variable scope error (line 693-697)
   - Fixed undefined `col` variable (line 900)

2. **InstrumentSequencer.py**
   - Removed incorrect `_render_note_length_leds` override (line 425-448)
   - Fixed pitch calculation to use direct MIDI values instead of array lookup (line 167)
   - Updated `_get_note_color` signature (line 191)

3. **StepSequencer.py**
   - Added comprehensive mode detection logging (lines 143-194)
   - Added track select button logging (lines 787-788)
   - Added note length application logging (lines 850-866)

4. **ClipSequencer.py**
   - Added missing methods: `is_audio_mode`, `render_view_leds`, `set_view_mode` (lines 205-265)

## Deployment Status

**Issue**: Logging added to StepSequencer.py is not appearing in Ableton log
**Possible Causes**:
1. Python syntax error preventing module load
2. Deployment script not copying files correctly
3. Ableton using cached .pyc files
4. Import error in modified files

## Next Steps

1. ✅ Verify Python syntax in all modified files
2. ✅ Check deployment script is copying files to correct location
3. ✅ Clear Python cache (.pyc files) before deployment
4. ✅ Add simple test logging to verify code is loading
5. ⏳ Test each mode individually after successful deployment

## Testing Checklist

### Instrument Mode:
- [ ] Press USER button - enters instrument mode (not drum mode)
- [ ] See BLUE/CYAN/OFF colors for scale awareness
- [ ] Press track select buttons (0-7) - note length changes
- [ ] LEDs update to show selected note length
- [ ] Grid refreshes when note length changes

### Audio Clip Mode:
- [ ] Load AIF/WAV file
- [ ] Press USER button - enters audio clip mode (not drum/piano)
- [ ] Track select buttons control view/zoom
- [ ] Grid shows waveform or audio markers
- [ ] Can adjust audio clip properties

### Drum Mode:
- [ ] Load drum rack or drum clip
- [ ] Press USER button - enters drum mode
- [ ] Simple GREEN/BLUE coloring (no scale colors)
- [ ] Track select buttons work for note length
- [ ] Function buttons work (Clear, Copy, Paste, Fill)
