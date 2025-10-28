from __future__ import absolute_import, print_function, unicode_literals
import Live
from .SequencerBase import SequencerBase

class InstrumentSequencer(SequencerBase):
    """
    Melodic instrument sequencer functionality.
    Handles scale detection, chromatic notes, and scale-aware visualization.
    """
    
    def __init__(self, control_surface, song, logger=None):
        """
        Initialize the instrument sequencer.
        
        Args:
            control_surface: The main APC40 control surface instance
            song: The Live.Song.Song instance
            logger: Optional SequencerLogger instance
        """
        super(InstrumentSequencer, self).__init__(control_surface, song, logger)
        
        # Melodic instrument uses full chromatic range (0-127)
        self._row_note_offsets = list(range(128))
        self._note_base = 48  # Start at middle C (C3)
        self._selected_note = 0
        
        # Scale detection
        self._current_scale = set()
        self._root_note = 0
        self._scale_name = "Chromatic"
        self._last_scale_check_time = 0.0
        
        # Scale definitions (semitone intervals from root)
        self._scales = {
            "Major": [0, 2, 4, 5, 7, 9, 11],
            "Minor": [0, 2, 3, 5, 7, 8, 10],
            "Dorian": [0, 2, 3, 5, 7, 9, 10],
            "Phrygian": [0, 1, 3, 5, 7, 8, 10],
            "Lydian": [0, 2, 4, 6, 7, 9, 11],
            "Mixolydian": [0, 2, 4, 5, 7, 9, 10],
            "Locrian": [0, 1, 3, 5, 6, 8, 10],
            "Diminished": [0, 2, 3, 5, 6, 8, 9, 11],
            "Whole Tone": [0, 2, 4, 6, 8, 10],
            "Harmonic Minor": [0, 2, 3, 5, 7, 8, 11],
            "Melodic Minor": [0, 2, 3, 5, 7, 9, 11],
            "Blues": [0, 3, 5, 6, 7, 10],
            "Pentatonic Major": [0, 2, 4, 7, 9],
            "Pentatonic Minor": [0, 3, 5, 7, 10],
            "Chromatic": list(range(12))
        }
        
        # Chromatic note tracking for blink animation
        self._newly_chromatic_notes = set()
        self._chromatic_blink_count = 0
        self._chromatic_blink_max = 10
        
    # ==================== SCALE DETECTION ====================
    
    def detect_scale(self):
        """
        Detect the current scale from Live's song settings.
        Updates internal scale state for visualization.
        """
        try:
            # Get scale info from Live
            if hasattr(self._song, 'root_note') and hasattr(self._song, 'scale_name'):
                root = int(self._song.root_note)  # 0-11 (C=0)
                scale_name = str(self._song.scale_name)
                
                # Check if scale changed
                if root != self._root_note or scale_name != self._scale_name:
                    old_scale = self._current_scale.copy()
                    self._root_note = root
                    self._scale_name = scale_name
                    
                    # Build scale set
                    self._build_scale()
                    
                    # Find newly chromatic notes
                    if old_scale:
                        self._newly_chromatic_notes = old_scale - self._current_scale
                        if self._newly_chromatic_notes:
                            self._chromatic_blink_count = 0
                            self._log_info("SCALE CHANGED: %s %s (%d chromatic notes now)" % 
                                         (self._get_note_name(root), scale_name, 
                                          len(self._newly_chromatic_notes)))
                    
                    self._log_info("Scale: %s %s (%d notes in scale)" % 
                                 (self._get_note_name(root), scale_name, len(self._current_scale)))
            else:
                # No scale info, use chromatic
                self._scale_name = "Chromatic"
                self._build_scale()
                
        except Exception as e:
            self._log_error("detect_scale", e)
            # Fallback to chromatic
            self._scale_name = "Chromatic"
            self._build_scale()
    
    def _build_scale(self):
        """Build the scale set based on current root and scale name."""
        try:
            # Get scale intervals
            intervals = self._scales.get(self._scale_name, self._scales["Chromatic"])
            
            # Build full scale across all octaves
            self._current_scale = set()
            for octave in range(11):  # 0-10 covers MIDI 0-127
                for interval in intervals:
                    note = (octave * 12) + self._root_note + interval
                    if 0 <= note <= 127:
                        self._current_scale.add(note)
            
        except Exception as e:
            self._log_error("_build_scale", e)
            # Fallback to all notes
            self._current_scale = set(range(128))
    
    def _get_note_name(self, note_number):
        """Get the name of a note (e.g., C, C#, D)."""
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return note_names[note_number % 12]
    
    def is_note_in_scale(self, note):
        """Check if a note is in the current scale."""
        return note in self._current_scale
    
    def is_root_note(self, note):
        """Check if a note is the root note of the scale."""
        return (note % 12) == self._root_note
    
    # ==================== GRID RENDERING ====================
    
    def refresh_grid(self, matrix_rows):
        """
        Refresh the grid to show current notes with scale-aware coloring.
        
        Args:
            matrix_rows: The matrix button rows
        """
        clip = self._get_cached_clip()
        if clip is None:
            self._clear_all_leds(matrix_rows)
            return
        
        try:
            # Get loop length for boundary checking
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
            note_len = self._note_lengths[self._note_length_index]
            
            # Clear grid first
            self._clear_all_leds(matrix_rows)
            
            # Handle chromatic blink animation
            blink_on = True
            if self._newly_chromatic_notes and self._chromatic_blink_count < self._chromatic_blink_max:
                blink_on = (self._chromatic_blink_count % 2) == 0
                self._chromatic_blink_count += 1
                if self._chromatic_blink_count >= self._chromatic_blink_max:
                    self._newly_chromatic_notes.clear()
            
            # Render each visible row (TOP row = HIGHEST note)
            for row in range(self._rows_visible):
                # TOP row (row 0) = highest note, BOTTOM row (row 4) = lowest note
                # For InstrumentSequencer, pitch is directly calculated from note_base
                pitch = (self._note_base + self._rows_visible - 1) - row
                
                if pitch < 0 or pitch > 127:
                    continue
                
                # Check each column for notes
                for col in range(self._steps_per_page):
                    step = col + self._time_page * self._steps_per_page
                    start = step * note_len
                    
                    if start >= loop_length:
                        continue
                    
                    # Check for notes at this step
                    has_note = self._check_note_at_step(clip, pitch, start, note_len)
                    
                    # Determine color based on scale and note state
                    color = self._get_note_color(pitch, has_note, pitch, blink_on)
                    
                    self._set_pad_led_color(col, row, color, matrix_rows)
            
        except Exception as e:
            self._log_error("refresh_grid", e)
    
    def _get_note_color(self, pitch, has_note, current_pitch, blink_on):
        """
        Get the appropriate color for a note based on scale and state.
        
        Args:
            pitch: MIDI pitch
            has_note: Whether a note exists at this position
            current_pitch: The pitch being rendered (for selected row checking)
            blink_on: Whether blink animation is on
            
        Returns:
            int: LED color value
        """
        # Check if this note just became chromatic (blink animation)
        if pitch in self._newly_chromatic_notes:
            if has_note:
                return self._LED_ORANGE if blink_on else self._LED_OFF
            else:
                return self._LED_OFF
        
        # Root note coloring (always show cyan for root)
        if self.is_root_note(pitch):
            if has_note:
                return self._LED_GREEN
            else:
                return self._LED_CYAN
        
        # In-scale note coloring
        if self.is_note_in_scale(pitch):
            if has_note:
                return self._LED_GREEN
            else:
                # Dim blue for available in-scale notes
                return self._LED_BLUE
        else:
            # Chromatic (out of scale) note coloring
            if has_note:
                return self._LED_ORANGE
            else:
                # Chromatic notes available - show as OFF
                return self._LED_OFF
    
    def _check_note_at_step(self, clip, pitch, start, note_len):
        """
        Check if there's a note at the given step.
        
        Args:
            clip: The clip to check
            pitch: MIDI pitch
            start: Start time in beats
            note_len: Note length in beats
            
        Returns:
            bool: True if note exists
        """
        try:
            tolerance = 0.001
            search_start = max(0.0, start - tolerance)
            search_duration = max(tolerance * 2, 0.001)
            
            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(pitch, 1, search_start, search_duration)
            else:
                notes = clip.get_notes(search_start, pitch, search_duration, 1)
            
            return notes and len(notes) > 0
            
        except Exception as e:
            self._log_error("_check_note_at_step", e)
            return False
    
    # ==================== NOTE OPERATIONS ====================
    
    def toggle_note(self, col, row, matrix_rows):
        """
        Toggle a note on/off at the given grid position.
        
        Args:
            col: Column index
            row: Row index
            matrix_rows: The matrix button rows
            
        Returns:
            bool: True if operation succeeded
        """
        try:
            # Calculate pitch (TOP row = HIGHEST note)
            row_offset = (self._note_base + self._rows_visible - 1) - row
            
            if row_offset < 0 or row_offset >= len(self._row_note_offsets):
                return False
            
            pitch = self._row_note_offsets[row_offset]
            step = col + self._time_page * self._steps_per_page
            note_len = self._note_lengths[self._note_length_index]
            start = step * note_len
            
            # Get clip
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            # Check loop bounds
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
            if start >= loop_length:
                return False
            
            # Check for existing note
            tolerance = 0.001
            search_start = max(0.0, start - tolerance)
            search_duration = max(tolerance * 2, 0.001)
            
            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(pitch, 1, search_start, search_duration)
            else:
                existing = clip.get_notes(search_start, pitch, search_duration, 1)
            
            if existing and len(existing) > 0:
                # Remove note
                note = existing[0]
                if hasattr(note, 'pitch'):
                    note_pitch = note.pitch
                    note_time = note.start_time
                    note_duration = note.duration
                else:
                    note_pitch = note[0]
                    note_time = note[1]
                    note_duration = note[2]
                
                if hasattr(clip, 'remove_notes_extended'):
                    clip.remove_notes_extended(note_pitch, 1, note_time, note_duration)
                else:
                    clip.remove_notes(note_time, note_pitch, note_duration, 1)
                
                self._log_debug("Removed note: pitch=%d (%s) time=%.3f" % 
                              (pitch, self._get_note_name(pitch), start))
                
                # Update LED
                color = self._get_note_color(pitch, False, row_offset, True)
                self._set_pad_led_color(col, row, color, matrix_rows)
                
            else:
                # Add note
                velocity = 100  # Default velocity for melodic instruments
                mute = False
                
                # Create note using Live 12 API
                if hasattr(clip, 'add_new_notes'):
                    # Live 12 API - requires MidiNoteSpecification
                    note_spec = Live.Clip.MidiNoteSpecification(
                        pitch=int(pitch),
                        start_time=float(start),
                        duration=float(note_len),
                        velocity=int(velocity),
                        mute=False
                    )
                    clip.add_new_notes((note_spec,))
                else:
                    # Old API fallback
                    clip.set_notes(((pitch, start, note_len, velocity, mute),))
                
                in_scale = "in-scale" if self.is_note_in_scale(pitch) else "chromatic"
                self._log_debug("Added note: pitch=%d (%s) time=%.3f [%s]" % 
                              (pitch, self._get_note_name(pitch), start, in_scale))
                
                # Update LED
                color = self._get_note_color(pitch, True, row_offset, True)
                self._set_pad_led_color(col, row, color, matrix_rows)
            
            return True
            
        except Exception as e:
            self._log_error("toggle_note", e)
            return False
    
    # ==================== NAVIGATION ====================
    
    def navigate_up(self):
        """Navigate up (to higher notes)."""
        if self._note_base < 123:  # Leave room for 5 visible rows
            self._note_base += 1
            self._log_debug("Navigate up: base=%d, TOP ROW=note %d, BOTTOM ROW=note %d" % 
                          (self._note_base, 
                           self._note_base + self._rows_visible - 1,
                           self._note_base))
            return True
        return False
    
    def navigate_down(self):
        """Navigate down (to lower notes)."""
        if self._note_base > 0:
            self._note_base -= 1
            self._log_debug("Navigate down: base=%d, TOP ROW=note %d, BOTTOM ROW=note %d" % 
                          (self._note_base,
                           self._note_base + self._rows_visible - 1,
                           self._note_base))
            return True
        return False
    
    def navigate_left(self):
        """Navigate left (earlier steps)."""
        if self._time_page > 0:
            self._time_page -= 1
            self._log_debug("Navigate left: time_page=%d" % self._time_page)
            return True
        return False
    
    def navigate_right(self):
        """Navigate right (later steps)."""
        # Check if we can navigate right based on loop length
        loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
        note_len = self._note_lengths[self._note_length_index]
        next_page_start = (self._time_page + 1) * self._steps_per_page * note_len
        
        if next_page_start < loop_length:
            self._time_page += 1
            self._log_debug("Navigate right: time_page=%d" % self._time_page)
            return True
        return False
    
    def get_visible_note_range(self):
        """
        Get the range of visible notes.
        
        Returns:
            tuple: (lowest_note, highest_note)
        """
        lowest = self._note_base
        highest = self._note_base + self._rows_visible - 1
        return (lowest, highest)
    
    # ==================== MODE MANAGEMENT ====================
    
    def enter(self):
        """Enter instrument sequencer mode."""
        super(InstrumentSequencer, self).enter()
        
        # Detect scale on entry
        self.detect_scale()
        
        # Log entry info
        lowest, highest = self.get_visible_note_range()
        self._log_info("Melodic instrument: Full range (0-127), starting at %s%d" % 
                     (self._get_note_name(lowest), lowest // 12))
        self._log_info("Visible range: %s%d to %s%d" % 
                     (self._get_note_name(lowest), lowest // 12,
                      self._get_note_name(highest), highest // 12))
    
    def should_check_scale(self):
        """
        Check if it's time to re-check the scale (at loop boundaries).
        
        Returns:
            bool: True if scale should be checked
        """
        try:
            current_time = self._song.current_song_time
            
            # Check scale at loop boundaries
            if hasattr(self, '_last_scale_check_time'):
                if current_time < self._last_scale_check_time:
                    # Loop restarted
                    self._last_scale_check_time = current_time
                    return True
            else:
                self._last_scale_check_time = current_time
            
            return False
            
        except Exception as e:
            self._log_error("should_check_scale", e)
            return False
