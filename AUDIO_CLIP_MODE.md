# Audio Clip Mode - Expected Behavior

## What Audio Clips Are
- **AIF files** (Audio Interchange File Format)
- **WAV files** (Waveform Audio File Format)  
- **Other audio files** (MP3, FLAC, etc.)
- These have **waveforms** (stereo or mono audio), NOT piano rolls

## Expected Grid Display

### 8x5 Grid Layout (Audio Mode):
```
Row 0: Loop START markers (CYAN)
Row 1: Left channel waveform (STEREO) or unused (MONO)
Row 2: Warp markers / Middle display
Row 3: Right channel waveform (STEREO) or unused (MONO)  
Row 4: Loop END markers (CYAN)
```

### Waveform Visualization Colors:
- **CYAN**: Loop start/end markers
- **GREEN**: Mid-level audio signal
- **YELLOW**: Higher level audio
- **ORANGE**: Near-clipping level
- **RED**: Clipping audio
- **OFF (dark)**: No audio data

## Track Select Buttons (View/Zoom Controls)
When in audio clip mode, track select buttons should control the view:

- **Button 0**: Full clip view
- **Button 1**: 1 bar view (4 beats)
- **Button 2**: 2 bar view (8 beats)
- **Button 3**: 4 bar view (16 beats)
- **Button 4**: 8 bar view (32 beats)
- **Button 5**: 1/4 of clip (with BANK: 1/32)
- **Button 6**: 1/8 of clip (with BANK: 1/64)
- **Button 7**: 1/16 of clip (with BANK: 1/128)

**Current button should light GREEN**
**Available buttons should light DIM BLUE**

## Current Issue
Based on your report:
1. ✅ Audio clips ARE being detected: "Mode: Audio Clip (AIF/WAV detected)"
2. ❌ But track select buttons show no response
3. ❌ Grid may not be showing waveform (showing wrong colors?)

## What to Check in Log
After pressing track select buttons in audio mode, you should see:
```
[AUDIO_SAMPLE] Audio view mode request: index=X bank_effective=False
[AUDIO_SAMPLE] Audio view mode set to X
```

If these don't appear, the button handler isn't reaching the audio clip code.

## Next Debug Steps
1. Load an audio clip (AIF or WAV)
2. Press USER button
3. Check Sequencer_Debugger.txt - does it say "Audio clip mode active"?
4. Press track select buttons (0-7)
5. Do you see AUDIO_SAMPLE logs?
6. What colors do you see on the 8x5 grid?

The logging fix I just deployed will show if note length changes are being applied.
