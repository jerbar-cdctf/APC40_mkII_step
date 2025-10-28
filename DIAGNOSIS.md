# ROOT CAUSE IDENTIFIED

## Problem
Melodic instrument clips are being detected as DRUM mode, causing:
1. ❌ No chromatic LED display (BLUE/CYAN/ORANGE)
2. ❌ Track select buttons not working for note length
3. ❌ Wrong sequencer mode loaded

## Evidence from Log (22:10:52)
```
[22:10:52.679] Found 19 notes in clip  
[22:10:52.680] Mode: Drum (detected pattern: 10 notes, 17 semitone range)
```

## Current Detection Logic (INCORRECT)
```python
if len(pitches) <= 16 and pitch_range <= 24:
    return DRUM_SEQUENCER  # TOO AGGRESSIVE!
```

This catches melodic bass lines, simple melodies, etc.

## Solution
**Priority Detection Order:**
1. ✅ Check for audio clip (`clip.is_audio_clip`) → ClipSequencer
2. ✅ Check for drum rack device (`can_have_drum_pads`) → DrumSequencer  
3. ⚠️ **NEW**: Check for melodic device (Operator, Wavetable, Sampler in melodic mode) → InstrumentSequencer
4. ⚠️ **IMPROVED**: Only use note analysis as LAST resort
5. ⚠️ **DEFAULT**: Assume InstrumentSequencer (safer default than DrumSequencer)

## Immediate Fix
Change default from DrumSequencer to InstrumentSequencer when uncertain.

## Better Long-term Fix
Add device name detection:
- If device name contains: "Operator", "Analog", "Wavetable", "Electric", "Tension" → InstrumentSequencer
- Only use note-based heuristics for clips without clear device indicators
