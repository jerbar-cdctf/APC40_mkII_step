from __future__ import absolute_import, print_function, unicode_literals
import Live
from .SequencerBase import SequencerBase

class ClipSequencer(SequencerBase):
    """
    Audio clip sequencer functionality.
    Handles audio clip detection, waveform visualization, and audio-specific controls.
    """
    
    def __init__(self, control_surface, song, logger=None):
        """
        Initialize the clip sequencer.
        
        Args:
            control_surface: The main APC40 control surface instance
            song: The Live.Song.Song instance
            logger: Optional SequencerLogger instance
        """
        super(ClipSequencer, self).__init__(control_surface, song, logger)
        
        # Audio clip state
        self._audio_clip_info = {}
        self._bank_mode = False  # ALT mode for extended controls
        self._view_mode = 0  # 0=full, 1-4=bars, 5-7=fractions
        self._zoom_pages = 1  # Number of pages for current view
        
        # Warp markers
        self._warp_markers = []
        
    # ==================== AUDIO CLIP DETECTION ====================
    
    def detect_audio_clip(self):
        """
        Detect if the current clip is an audio clip and extract info.
        
        Returns:
            bool: True if audio clip detected
        """
        try:
            clip = self._get_cached_clip()
            if clip is None:
                return False
            
            # Check if it's an audio clip
            is_audio = False
            if hasattr(clip, 'is_audio_clip'):
                is_audio = clip.is_audio_clip
            else:
                # Fallback: check for MIDI-specific properties
                is_audio = not (hasattr(clip, 'get_notes') or hasattr(clip, 'get_notes_extended'))
            
            if not is_audio:
                return False
            
            # Extract audio clip info
            self._audio_clip_info = {
                'length_beats': float(clip.length),
                'loop_start': float(clip.loop_start),
                'loop_end': float(clip.loop_end),
                'is_warped': bool(getattr(clip, 'warping', False)),
                'channels': 2,  # Default to stereo
                'sample_rate': 44100  # Default
            }
            
            # Try to get sample info (may not be available for warped clips)
            if hasattr(clip, 'sample'):
                sample = clip.sample
                if sample:
                    if hasattr(sample, 'length'):
                        self._audio_clip_info['sample_length'] = sample.length
                    if hasattr(sample, 'sample_rate'):
                        self._audio_clip_info['sample_rate'] = sample.sample_rate
            
            # Detect channels (stereo vs mono)
            # Note: This is a simplified detection
            self._audio_clip_info['channels'] = 2  # Assume stereo by default
            
            self._log_info("Audio clip detected: %.1f beats, %s, %d channels" % 
                         (self._audio_clip_info['length_beats'],
                          "warped" if self._audio_clip_info['is_warped'] else "unwarped",
                          self._audio_clip_info['channels']))
            
            return True
            
        except Exception as e:
            self._log_error("detect_audio_clip", e)
            return False
    
    # ==================== GRID RENDERING ====================
    
    def refresh_grid(self, matrix_rows):
        """
        Refresh the grid to show audio waveform visualization.
        
        Args:
            matrix_rows: The matrix button rows
        """
        clip = self._get_cached_clip()
        if clip is None or not self._audio_clip_info:
            self._clear_all_leds(matrix_rows)
            return
        
        try:
            # Clear grid first
            self._clear_all_leds(matrix_rows)
            
            # Calculate visible time range
            loop_length = self._audio_clip_info['loop_end'] - self._audio_clip_info['loop_start']
            beats_per_column = loop_length / (self._steps_per_page * self._zoom_pages)
            
            # Render waveform visualization
            channels = self._audio_clip_info['channels']
            
            for col in range(self._steps_per_page):
                # Calculate time position for this column
                time_offset = col * beats_per_column
                absolute_time = self._audio_clip_info['loop_start'] + time_offset
                
                if absolute_time >= self._audio_clip_info['loop_end']:
                    continue
                
                # Row 0: Loop START markers
                if self._is_loop_start_marker(absolute_time):
                    self._set_pad_led_color(col, 0, self._LED_GREEN, matrix_rows)
                
                # Row 1: Left channel (stereo) or unused (mono)
                if channels == 2:
                    intensity = self._get_waveform_intensity(clip, absolute_time, 0)
                    color = self._get_intensity_color(intensity)
                    self._set_pad_led_color(col, 1, color, matrix_rows)
                
                # Row 2: Warp markers
                if self._has_warp_marker(absolute_time, beats_per_column):
                    self._set_pad_led_color(col, 2, self._LED_ORANGE, matrix_rows)
                
                # Row 3: Right channel (stereo) or unused (mono)
                if channels == 2:
                    intensity = self._get_waveform_intensity(clip, absolute_time, 1)
                    color = self._get_intensity_color(intensity)
                    self._set_pad_led_color(col, 3, color, matrix_rows)
                
                # Row 4: Loop END markers
                if self._is_loop_end_marker(absolute_time, beats_per_column):
                    self._set_pad_led_color(col, 4, self._LED_RED, matrix_rows)
            
        except Exception as e:
            self._log_error("refresh_grid", e)
    
    def _get_waveform_intensity(self, clip, time, channel):
        """
        Get waveform intensity at a given time (simplified).
        
        Args:
            clip: The audio clip
            time: Time in beats
            channel: Channel index (0=left, 1=right)
            
        Returns:
            float: Intensity value (0.0-1.0)
        """
        # This is a simplified implementation
        # In a full implementation, you would analyze the actual audio data
        # For now, return a default medium intensity
        return 0.5
    
    def _get_intensity_color(self, intensity):
        """
        Get LED color based on waveform intensity.
        
        Args:
            intensity: Intensity value (0.0-1.0)
            
        Returns:
            int: LED color value
        """
        if intensity > 0.9:
            return self._LED_RED  # Clipping
        elif intensity > 0.7:
            return self._LED_ORANGE  # Near edge
        elif intensity > 0.5:
            return self._LED_YELLOW  # Near orange
        elif intensity > 0.3:
            return self._LED_GREEN  # Ideal level
        elif intensity > 0.1:
            return self._LED_LIME  # Light green
        else:
            return self._LED_OFF  # No intensity
    
    def _is_loop_start_marker(self, time):
        """Check if time is at loop start."""
        return abs(time - self._audio_clip_info['loop_start']) < 0.01
    
    def _is_loop_end_marker(self, time, beats_per_column):
        """Check if time is at loop end."""
        return abs(time - self._audio_clip_info['loop_end']) < beats_per_column
    
    def _has_warp_marker(self, time, tolerance):
        """Check if there's a warp marker near this time."""
        for marker_time in self._warp_markers:
            if abs(time - marker_time) < tolerance:
                return True
        return False
    
    def is_audio_mode(self):
        """
        Check if currently in audio mode.
        
        Returns:
            bool: True if audio clip is loaded
        """
        return bool(self._audio_clip_info)
    
    def render_view_leds(self, track_select_buttons, bank_pressed):
        """
        Render view mode LEDs on track select buttons for audio clips.
        
        Args:
            track_select_buttons: List of track select buttons
            bank_pressed: Whether bank/shift is pressed
        """
        try:
            if not track_select_buttons:
                return
            
            # Light up buttons to show view modes
            # Button 0: Full view
            # Buttons 1-4: Bar views (1, 2, 4, 8 bars)
            # Buttons 5-7: Fractional views (1/2, 1/4, 1/8)
            
            for idx in range(min(8, len(track_select_buttons))):
                btn = track_select_buttons[idx]
                if btn and hasattr(btn, 'send_value'):
                    if idx == self._view_mode:
                        # Current mode: bright green
                        btn.send_value(self._LED_GREEN, True)
                    else:
                        # Available mode: dim blue
                        btn.send_value(self._LED_BLUE, True)
                        
        except Exception as e:
            self._log_error("render_view_leds", e)
    
    def set_view_mode(self, mode_index, bank_pressed=False):
        """
        Set the view/zoom mode for audio clip.
        
        Args:
            mode_index: View mode index (0-7)
            bank_pressed: Whether bank/shift is pressed
        """
        try:
            self._view_mode = mode_index
            self._log_info("Audio view mode set to %d" % mode_index)
            
            # Calculate zoom pages based on view mode
            if mode_index == 0:
                self._zoom_pages = 1  # Full view
            elif mode_index <= 4:
                self._zoom_pages = [1, 2, 4, 8][mode_index - 1] if mode_index > 0 else 1
            else:
                self._zoom_pages = [0.5, 0.25, 0.125][mode_index - 5] if mode_index >= 5 else 1
            
        except Exception as e:
            self._log_error("set_view_mode", e)
    
    # ==================== WARP CONTROLS ====================
    
    def toggle_warp_marker(self, col):
        """
        Toggle warp marker at the given column.
        
        Args:
            col: Column index
            
        Returns:
            bool: True if operation succeeded
        """
        try:
            clip = self._ensure_clip()
            if clip is None or not self._audio_clip_info:
                return False
            
            # Calculate beat position
            loop_length = self._audio_clip_info['loop_end'] - self._audio_clip_info['loop_start']
            beats_per_column = loop_length / (self._steps_per_page * self._zoom_pages)
            beat_position = self._audio_clip_info['loop_start'] + (col * beats_per_column)
            
            # Check if marker exists
            if hasattr(clip, 'get_warp_markers'):
                markers = clip.get_warp_markers()
                marker_exists = any(abs(m - beat_position) < 0.01 for m in markers)
                
                if marker_exists:
                    # Remove marker
                    if hasattr(clip, 'remove_warp_marker'):
                        clip.remove_warp_marker(beat_position)
                        self._log_info("Removed warp marker at beat %.2f" % beat_position)
                else:
                    # Create marker
                    if hasattr(clip, 'create_warp_marker'):
                        clip.create_warp_marker(beat_position)
                        self._log_info("Created warp marker at beat %.2f" % beat_position)
                
                return True
            
            return False
            
        except Exception as e:
            self._log_error("toggle_warp_marker", e)
            return False
    
    def toggle_reverse(self):
        """Toggle reverse playback."""
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'is_reversed'):
                clip.is_reversed = not clip.is_reversed
                state = "REVERSED" if clip.is_reversed else "NORMAL"
                self._log_info("Audio playback: %s" % state)
                return True
            
            return False
            
        except Exception as e:
            self._log_error("toggle_reverse", e)
            return False
    
    def set_gain(self, gain_db):
        """
        Set clip gain.
        
        Args:
            gain_db: Gain in dB (-12, -6, 0, +3, +6)
        """
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'gain'):
                # Convert dB to linear
                gain_linear = pow(10.0, gain_db / 20.0)
                clip.gain = gain_linear
                self._log_info("Gain set to %.1f dB (linear=%.2f)" % (gain_db, gain_linear))
                return True
            
            return False
            
        except Exception as e:
            self._log_error("set_gain", e)
            return False
    
    def cycle_warp_mode(self):
        """Cycle through warp modes."""
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'warp_mode'):
                # Cycle: Beats (0) → Complex/RAM (4) → Complex Pro/HiQ (6)
                modes = [0, 4, 6]
                mode_names = {0: "Beats", 4: "Complex/RAM", 6: "Complex Pro/HiQ"}
                
                current = clip.warp_mode
                try:
                    current_index = modes.index(current)
                    next_index = (current_index + 1) % len(modes)
                except ValueError:
                    next_index = 0
                
                clip.warp_mode = modes[next_index]
                self._log_info("Warp mode: %s" % mode_names[modes[next_index]])
                return True
            
            return False
            
        except Exception as e:
            self._log_error("cycle_warp_mode", e)
            return False
    
    def set_pitch(self, semitones):
        """
        Set pitch adjustment.
        
        Args:
            semitones: Pitch in semitones (-48 to +48)
        """
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'pitch_coarse'):
                clip.pitch_coarse = int(semitones)
                clip.pitch_fine = 0  # Reset fine pitch
                self._log_info("Pitch set to %+d semitones" % semitones)
                return True
            
            return False
            
        except Exception as e:
            self._log_error("set_pitch", e)
            return False
    
    # ==================== LOOP CONTROLS ====================
    
    def set_loop_start(self, beat_position):
        """Set loop start position."""
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'loop_start'):
                clip.loop_start = float(beat_position)
                self._audio_clip_info['loop_start'] = float(beat_position)
                self._log_info("Loop start set to beat %.2f" % beat_position)
                return True
            
            return False
            
        except Exception as e:
            self._log_error("set_loop_start", e)
            return False
    
    def set_loop_end(self, beat_position):
        """Set loop end position."""
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            if hasattr(clip, 'loop_end'):
                clip.loop_end = float(beat_position)
                self._audio_clip_info['loop_end'] = float(beat_position)
                self._log_info("Loop end set to beat %.2f" % beat_position)
                return True
            
            return False
            
        except Exception as e:
            self._log_error("set_loop_end", e)
            return False
    
    def loop_bar(self, bar_number):
        """
        Loop a specific bar.
        
        Args:
            bar_number: Bar number (1-based)
        """
        try:
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            # Calculate bar boundaries (4 beats per bar)
            start = float((bar_number - 1) * 4)
            end = float(bar_number * 4)
            
            if hasattr(clip, 'loop_start') and hasattr(clip, 'loop_end'):
                clip.loop_start = start
                clip.loop_end = end
                clip.looping = True
                
                self._audio_clip_info['loop_start'] = start
                self._audio_clip_info['loop_end'] = end
                
                self._log_info("Looping bar %d (beats %.1f-%.1f)" % (bar_number, start, end))
                return True
            
            return False
            
        except Exception as e:
            self._log_error("loop_bar", e)
            return False
    
    # ==================== VIEW/ZOOM CONTROLS ====================
    
    def toggle_bank_mode(self):
        """Toggle bank (ALT) mode."""
        self._bank_mode = not self._bank_mode
        self._log_info("Bank mode: %s" % ("ON" if self._bank_mode else "OFF"))
        return self._bank_mode
    
    # ==================== MODE MANAGEMENT ====================
    
    def enter(self):
        """Enter audio clip sequencer mode."""
        super(ClipSequencer, self).enter()
        
        # Detect audio clip and extract info
        if self.detect_audio_clip():
            self._log_info("Audio clip mode active")
            self._log_info("Loop: %.1f to %.1f beats" % 
                         (self._audio_clip_info['loop_start'],
                          self._audio_clip_info['loop_end']))
        else:
            self._log_info("No audio clip detected")
    
    def exit(self):
        """Exit audio clip sequencer mode."""
        super(ClipSequencer, self).exit()
        self._audio_clip_info = {}
        self._warp_markers = []
        self._bank_mode = False
        self._view_mode = 0
