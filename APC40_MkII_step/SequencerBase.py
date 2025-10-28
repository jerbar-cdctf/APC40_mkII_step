from __future__ import absolute_import, print_function, unicode_literals
import Live
from .SequencerLogger import SequencerLogger

class SequencerBase(object):
    """
    Base class for all sequencer modes (Drum, Instrument, Clip).
    Contains shared functionality like LED management, clip access, and common utilities.
    """
    
    def __init__(self, control_surface, song, logger=None):
        """
        Initialize the base sequencer with common dependencies.
        
        Args:
            control_surface: The main APC40 control surface instance
            song: The Live.Song.Song instance
            logger: Optional SequencerLogger instance
        """
        self._cs = control_surface
        self._song = song
        self._logger = logger if logger else SequencerLogger()
        
        # LED color palette (APC40 MkII)
        self._LED_OFF = 0
        self._LED_GREEN = 21
        self._LED_RED = 5
        self._LED_YELLOW = 13
        self._LED_ORANGE = 9
        self._LED_BLUE = 79
        self._LED_PURPLE = 81
        self._LED_DARK_PURPLE = 49
        self._LED_BROWN = 17
        self._LED_DARK_BROWN = 11
        self._LED_CYAN = 37
        self._LED_PINK = 57
        self._LED_LIME = 25
        self._LED_AMBER = 45
        self._LED_TEAL = 33
        self._LED_PEACH = 53
        self._LED_LIGHT_BLUE = 55
        
        # Common sequencer state
        self._mode = False
        self._steps_per_page = 8
        self._rows_visible = 5
        self._time_page = 0
        self._drum_row_base = 11  # Start at bottom (showing lowest notes: indices 11-15 = notes 36-40)
        
        # Note length settings (expanded down to 1/64, with longer lengths first)
        self._note_length_index = 0
        self._note_lengths = [2.0, 32.0, 16.0, 8.0, 4.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
        self._base_note_lengths = list(self._note_lengths)
        self._triplet_note_lengths = [length * (2.0 / 3.0) for length in self._note_lengths]
        self._septuplet_note_lengths = [length * (4.0 / 7.0) for length in self._note_lengths]
        self._current_note_length = self._note_lengths[0]

        # Note length color tables (aligned with note length indices)
        self._base_note_length_colors = [
            self._LED_ORANGE,      # 2.0 beats (half bar)
            self._LED_DARK_BROWN,  # 32 beats (8 bars)
            self._LED_BROWN,       # 16 beats (4 bars)
            self._LED_RED,         # 8 beats (2 bars)
            self._LED_YELLOW,      # 4 beats (1 bar)
            self._LED_GREEN,       # 1 beat (1/4 bar)
            self._LED_CYAN,        # 0.5 beats (1/8)
            self._LED_BLUE,        # 0.25 beats (1/16)
            self._LED_PURPLE,      # 0.125 beats (1/32)
            self._LED_PINK         # 0.0625 beats (1/64)
        ]
        self._triplet_note_length_colors = [
            self._LED_PEACH,
            self._LED_PINK,
            self._LED_AMBER,
            self._LED_PURPLE,
            self._LED_LIGHT_BLUE,
            self._LED_TEAL,
            self._LED_LIME,
            self._LED_CYAN,
            self._LED_BLUE,
            self._LED_DARK_PURPLE
        ]
        self._septuplet_note_length_colors = [
            self._LED_TEAL,
            self._LED_LIGHT_BLUE,
            self._LED_PEACH,
            self._LED_AMBER,
            self._LED_PURPLE,
            self._LED_LIME,
            self._LED_CYAN,
            self._LED_BLUE,
            self._LED_PINK,
            self._LED_DARK_PURPLE
        ]
        self._active_note_length_colors = list(self._base_note_length_colors)
        self._note_length_button_map = [0, 1, 2, 3, 4, 5, 6, 7, 5, 6]

        # Dim color lookup to support alternating full/dim patterns
        self._dim_color_map = {
            self._LED_ORANGE: self._LED_AMBER,
            self._LED_DARK_BROWN: self._LED_BROWN,
            self._LED_BROWN: self._LED_DARK_BROWN,
            self._LED_RED: self._LED_PEACH,
            self._LED_YELLOW: self._LED_AMBER,
            self._LED_GREEN: self._LED_LIME,
            self._LED_CYAN: self._LED_LIGHT_BLUE,
            self._LED_BLUE: self._LED_TEAL,
            self._LED_PURPLE: self._LED_DARK_PURPLE,
            self._LED_PINK: self._LED_PEACH,
            self._LED_LIGHT_BLUE: self._LED_TEAL,
            self._LED_TEAL: self._LED_CYAN,
            self._LED_PEACH: self._LED_AMBER,
            self._LED_AMBER: self._LED_YELLOW,
            self._LED_DARK_PURPLE: self._LED_PURPLE
        }
        
        # Grid blink tracking
        self._grid_blink_states = {}

        # Loop settings (power-of-two up to 512 bars)
        self._loop_bars_options = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
        self._loop_bars_index = 0
        self._triplet_mode = False
        self._septuplet_mode = False
        
        # Playhead tracking
        self._last_blink_col = None
        self._blink_on = False
        self._blink_phase = 0
        self._current_tempo = 120.0
        
        # Track last interacted column
        self._last_interacted_col = None
        
    # ==================== CLIP MANAGEMENT ====================
    
    def _current_clip_slot(self):
        """
        Get the currently selected clip slot.
        
        Returns:
            Live.ClipSlot.ClipSlot or None
        """
        try:
            track = self._song.view.selected_track
            if track and hasattr(track, 'clip_slots'):
                # Live 12 API: Use selected_scene object, then find its index
                scene = self._song.view.selected_scene
                scenes = list(self._song.scenes)
                slot_index = scenes.index(scene)
                if 0 <= slot_index < len(track.clip_slots):
                    return track.clip_slots[slot_index]
        except Exception as e:
            self._log_error("_current_clip_slot", e)
        return None
    
    def _ensure_clip(self):
        """
        Get the current clip, creating one if necessary.
        
        Returns:
            Live.Clip.Clip or None
        """
        slot = self._current_clip_slot()
        if slot is None:
            # Fall back to cached clip if Live temporarily reports no slot
            if hasattr(self, '_cached_clip'):
                return self._cached_clip
            return None
            
        try:
            if slot.has_clip:
                clip = slot.clip
                if hasattr(self, '_cached_clip'):
                    self._cached_clip = clip
                    self._cached_clip_slot = slot
                return clip
            else:
                # Create a new clip if slot is empty
                try:
                    slot.create_clip(4.0)  # Create 4-bar clip by default
                    if slot.has_clip:
                        clip = slot.clip
                        if hasattr(self, '_cached_clip'):
                            self._cached_clip = clip
                            self._cached_clip_slot = slot
                        return clip
                except Exception as e:
                    self._log_error("create_clip", e)
        except Exception as e:
            self._log_error("_ensure_clip", e)
        return None
    
    def _get_cached_clip(self):
        """
        Get the current clip with caching for performance.
        
        Returns:
            Live.Clip.Clip or None
        """
        if not hasattr(self, '_cached_clip'):
            self._cached_clip = None
            self._cached_clip_slot = None
            
        current_slot = self._current_clip_slot()

        # If Live temporarily reports no selected slot, fall back to the last known clip
        if current_slot is None:
            return self._cached_clip

        refresh_needed = (current_slot != self._cached_clip_slot) or (self._cached_clip is None)
        if refresh_needed:
            clip = self._ensure_clip()
            if clip is not None:
                self._cached_clip_slot = current_slot
                self._cached_clip = clip

        return self._cached_clip
    
    def _invalidate_clip_cache(self):
        """Invalidate the clip cache when switching clips."""
        if hasattr(self, '_cached_clip'):
            self._cached_clip_slot = None
    
    # ==================== LED MANAGEMENT ====================
    
    def _set_pad_led_color(self, col, row, color_value, matrix_rows):
        """
        Set a specific pad LED to a color value.
        
        Args:
            col: Column index (0-7)
            row: Row index (0-4)
            color_value: LED color value from palette
            matrix_rows: The matrix button rows
        """
        try:
            if 0 <= row < len(matrix_rows) and 0 <= col < len(matrix_rows[row]):
                btn = matrix_rows[row][col]
                if btn and hasattr(btn, 'send_value'):
                    btn.send_value(color_value)
        except Exception as e:
            self._log_error("_set_pad_led_color", e)
    
    def _clear_all_leds(self, matrix_rows):
        """
        Turn off all matrix pad LEDs.
        
        Args:
            matrix_rows: The matrix button rows
        """
        try:
            for r in range(len(matrix_rows)):
                for c in range(len(matrix_rows[r])):
                    self._set_pad_led_color(c, r, self._LED_OFF, matrix_rows)
        except Exception as e:
            self._log_error("_clear_all_leds", e)
    
    def _clear_note_length_leds(self, track_select_buttons):
        """
        Turn off all note length button LEDs.
        
        Args:
            track_select_buttons: List of track select buttons
        """
        try:
            for btn in track_select_buttons:
                if btn and hasattr(btn, 'send_value'):
                    btn.send_value(self._LED_OFF)
        except Exception as e:
            self._log_error("_clear_note_length_leds", e)
    
    def _render_note_length_leds(self, track_select_buttons):
        """
        Light the selected note length button in orange, others off.
        
        Args:
            track_select_buttons: List of track select buttons
        """
        try:
            selected_button = self.get_button_index_for_length(self._note_length_index)
            for i, btn in enumerate(track_select_buttons):
                if btn and hasattr(btn, 'send_value'):
                    if selected_button is not None and i == selected_button:
                        btn.send_value(self.get_note_length_color(self._note_length_index))
                    else:
                        btn.send_value(self._LED_OFF)
        except Exception as e:
            self._log_error("_render_note_length_leds", e)

    def get_button_index_for_length(self, length_index):
        """Resolve the physical button index for the supplied note length index."""
        mapping = getattr(self, '_note_length_button_map', None)
        if mapping and 0 <= length_index < len(mapping):
            return mapping[length_index]
        return length_index if length_index >= 0 else None

    def get_note_length_color(self, index, dim=False):
        """Return the color associated with the supplied note length index."""
        colors = getattr(self, '_active_note_length_colors', self._base_note_length_colors)
        if 0 <= index < len(colors):
            color = colors[index]
        else:
            color = self._LED_ORANGE
        if dim:
            return self._dim_color_map.get(color, color)
        return color

    def get_dim_color(self, color):
        """Resolve a dimmer representation of the supplied color."""
        return self._dim_color_map.get(color, color)

    def get_color_for_duration(self, duration):
        """Return the nearest note length color for the supplied duration."""
        try:
            lengths = self._note_lengths if self._note_lengths else self._base_note_lengths
            if not lengths:
                return self._LED_ORANGE
            index = min(range(len(lengths)), key=lambda i: abs(lengths[i] - float(duration)))
            return self.get_note_length_color(index)
        except Exception:
            return self._LED_ORANGE

    def _reset_grid_blink_states(self):
        """Clear cached blink state for the grid."""
        self._grid_blink_states = {}

    def _register_grid_blink(self, row, col, pattern, subdivision_length):
        """Register a blink pattern for a grid cell synced to tempo."""
        key = (row, col)
        if not pattern or len(pattern) <= 1 or subdivision_length <= 0:
            if key in self._grid_blink_states:
                self._grid_blink_states.pop(key, None)
            return

        state = {
            'pattern': list(pattern),
            'subdivision': float(subdivision_length),
            'last_index': -1
        }
        self._grid_blink_states[key] = state

    def advance_grid_blink(self, matrix_rows):
        """Advance registered blink patterns using current song time."""
        if not self._grid_blink_states or self._song is None:
            return

        try:
            song_time = float(getattr(self._song, 'current_song_time', 0.0))
        except Exception:
            return

        stale = []
        for (row, col), state in list(self._grid_blink_states.items()):
            pattern = state.get('pattern')
            subdivision = state.get('subdivision', 0.0)
            if not pattern or subdivision <= 0:
                stale.append((row, col))
                continue
            if not (0 <= row < len(matrix_rows) and 0 <= col < len(matrix_rows[row])):
                stale.append((row, col))
                continue

            phase = int((song_time / subdivision) % len(pattern))
            if phase != state.get('last_index'):
                color_value = pattern[phase]
                self._set_pad_led_color(col, row, color_value, matrix_rows)
                state['last_index'] = phase

        for key in stale:
            self._grid_blink_states.pop(key, None)

    # ==================== BUTTON HELPERS ====================
    
    def _locate_matrix_button(self, sender, matrix_rows):
        """
        Find the (col, row) position of a matrix button.
        
        Args:
            sender: The button that was pressed
            matrix_rows: The matrix button rows
            
        Returns:
            tuple: (col, row) or None if not found
        """
        if sender is None:
            return None
        try:
            for r, row in enumerate(matrix_rows):
                for c, btn in enumerate(row):
                    if btn == sender:
                        return (c, r)
        except Exception as e:
            self._log_error("_locate_matrix_button", e)
        return None
    
    # ==================== LOOP MANAGEMENT ====================
    
    def _apply_loop_length(self):
        """Apply the selected loop length to the current clip."""
        clip = self._ensure_clip()
        if clip is None:
            return
            
        try:
            bars = self._loop_bars_options[self._loop_bars_index]
            loop_length = float(bars * 4.0)  # Convert bars to beats
            
            clip.loop_start = 0.0
            clip.loop_end = loop_length
            clip.end_marker = loop_length
            clip.looping = True
            
            # Also set arrangement loop
            self._song.loop_start = 0.0
            self._song.loop_length = loop_length
            self._song.loop = True
            
            self._log_info("Loop length set to %d bars (%.1f beats)" % (bars, loop_length))
            
            # Reset time page if now beyond loop end
            max_page = int(loop_length / (self._note_lengths[self._note_length_index] * self._steps_per_page))
            if self._time_page >= max_page:
                self._time_page = 0
                
        except Exception as e:
            self._log_error("_apply_loop_length", e)
    
    # ==================== LOGGING HELPERS ====================
    
    def _log_info(self, message):
        """Log an info message."""
        try:
            if self._logger:
                self._logger.log_info(message)
            else:
                self._cs.log_message("[INFO] " + str(message))
        except Exception:
            pass
    
    def _log_error(self, context, error):
        """Log an error message with context."""
        try:
            if self._logger:
                self._logger.log_error(context, error)
            else:
                self._cs.log_message("[ERROR] %s: %s" % (context, str(error)))
        except Exception:
            pass
    
    def _log_debug(self, message):
        """Log a debug message."""
        try:
            if self._logger:
                self._logger.log_debug(message)
            else:
                self._cs.log_message("[DEBUG] " + str(message))
        except Exception:
            pass

    # ==================== SUBDIVISION HANDLING ====================

    def apply_subdivision_mode(self):
        """Update internal note length tables based on triplet/septuplet flags."""
        try:
            if self._triplet_mode and self._septuplet_mode:
                # Triplet takes precedence; ensure mutual exclusivity
                self._septuplet_mode = False

            if self._triplet_mode:
                self._note_lengths = list(self._triplet_note_lengths)
                self._active_note_length_colors = list(self._triplet_note_length_colors)
                mode_name = "Triplet"
            elif self._septuplet_mode:
                self._note_lengths = list(self._septuplet_note_lengths)
                self._active_note_length_colors = list(self._septuplet_note_length_colors)
                mode_name = "Septuplet"
            else:
                self._note_lengths = list(self._base_note_lengths)
                self._active_note_length_colors = list(self._base_note_length_colors)
                mode_name = "Straight"

            self._note_length_index = max(0, min(self._note_length_index, len(self._note_lengths) - 1))
            self._current_note_length = self._note_lengths[self._note_length_index]

            clip = self._get_cached_clip()
            if clip and hasattr(clip, 'grid_quantization'):
                self._configure_clip_quantization(clip)

            self._log_info("Subdivision mode applied: %s (current length=%.4f)" % (mode_name, self._current_note_length))

        except Exception as e:
            self._log_error("apply_subdivision_mode", e)

    def _configure_clip_quantization(self, clip):
        """Set clip grid quantization according to current subdivision."""
        try:
            if not clip:
                return

            if self._triplet_mode:
                clip.is_triplet_grid = True
                clip.grid_quantization = Live.Clip.GridQuantization.g_sixteenth
                if hasattr(clip, 'triplet_grid_quantization'):
                    clip.triplet_grid_quantization = Live.Clip.GridQuantization.g_sixteenth
            elif self._septuplet_mode:
                clip.is_triplet_grid = False
                clip.grid_quantization = Live.Clip.GridQuantization.g_thirtysecond
            else:
                clip.is_triplet_grid = False
                clip.grid_quantization = Live.Clip.GridQuantization.g_sixteenth

        except Exception as e:
            self._log_error("_configure_clip_quantization", e)
    
    # ==================== MODE MANAGEMENT ====================
    
    def enter(self):
        """Enter sequencer mode. Override in subclasses."""
        self._mode = True
        self._invalidate_clip_cache()
        self._log_info("Entering sequencer mode")
    
    def exit(self):
        """Exit sequencer mode. Override in subclasses."""
        self._mode = False
        self._invalidate_clip_cache()
        self._log_info("Exiting sequencer mode")
    
    def is_active(self):
        """Check if sequencer mode is active."""
        return self._mode
    
    # ==================== TEMPO TRACKING ====================
    
    def _on_tempo_changed(self):
        """Handle tempo changes for dynamic tick rate adjustment."""
        try:
            self._current_tempo = float(self._song.tempo)
            self._log_debug("Tempo changed to %.1f BPM" % self._current_tempo)
        except Exception as e:
            self._log_error("_on_tempo_changed", e)
