from __future__ import absolute_import, print_function, unicode_literals
import Live

# LOGGING CONTROL: Set to False to disable all logging
ENABLE_LOGGING = False

class StepSequencer(object):
    def __init__(self, control_surface, song, shift_button, user_button, pan_button, sends_button,
                 left_button, right_button, up_button, down_button,
                 scene_launch_buttons_raw, clip_stop_buttons_raw, matrix_rows_raw, knob_controls, track_select_buttons,
                 device_controls=None, prev_device_button=None, next_device_button=None, 
                 stop_all_button=None, master_button=None):
        self._cs = control_surface
        self._song = song
        self._enable_logging = ENABLE_LOGGING
        self._shift_button = shift_button
        self._user_button = user_button
        self._pan_button = pan_button
        self._sends_button = sends_button
        self._left_button = left_button
        self._right_button = right_button
        self._up_button = up_button
        self._down_button = down_button
        self._scene_launch_buttons_raw = list(scene_launch_buttons_raw)
        self._stop_all_button = stop_all_button
        self._master_button = master_button
        # Clip stop buttons (beneath matrix) to control loop length in sequencer mode
        # Normalize clip stop buttons into a flat list of ButtonElements
        try:
            raw = clip_stop_buttons_raw
            # If a ButtonMatrixElement, iterate and flatten
            try:
                flattened = []
                for row in raw:
                    if isinstance(row, (list, tuple)):
                        for btn in row:
                            flattened.append(btn)
                    else:
                        # Already a button element
                        flattened.append(row)
                self._clip_stop_buttons_raw = flattened
            except Exception:
                # Fallback to list() if simple iterable
                self._clip_stop_buttons_raw = list(raw)
        except Exception:
            self._clip_stop_buttons_raw = []
        self._matrix_rows_raw = [list(r) for r in matrix_rows_raw]
        self._knob_controls = list(knob_controls)
        self._track_select_buttons = list(track_select_buttons)
        self._device_controls = list(device_controls) if device_controls else []
        self._prev_device_button = prev_device_button
        self._next_device_button = next_device_button

        self._mpe_channels = list(range(2, 16))
        # Track last values for assignable knobs (for LED ring feedback)
        try:
            self._assignable_knob_values = [0] * len(self._knob_controls)
        except Exception:
            self._assignable_knob_values = []
        # Track separate per-mode values for assignable knobs: Pitch (no shift) and Slide (with shift)
        try:
            self._assignable_knob_pitch_values = [0] * len(self._knob_controls)
            self._assignable_knob_slide_values = [0] * len(self._knob_controls)
        except Exception:
            self._assignable_knob_pitch_values = []
            self._assignable_knob_slide_values = []

        # Sequencer state
        self._mode = False
        self._steps_per_page = 8
        self._rows_visible = 5  # Use all 5 matrix rows for drum input
        # PERFORMANCE: Cache clip reference to avoid expensive lookups every tick
        self._cached_clip = None
        self._clip_cache_valid = False
        # FULL PIANO ROLL: All 128 MIDI notes (0-127)
        # Grid shows 5 notes at a time, navigation scrolls through full range
        # ABLETON LAYOUT: Top row = higher notes, Bottom row = lower notes
        self._row_note_offsets = list(range(128))  # Full MIDI range 0-127
        self._drum_row_base = 0
        self._time_page = 0
        self._note_length_index = 0
        # Note lengths in beats: 1/2 bar, 8 bars, 4 bars, 2 bars, 1 bar, 1/4 bar, 1/8th bar, 1/16th bar
        self._note_lengths = [2.0, 32.0, 16.0, 8.0, 4.0, 1.0, 0.5, 0.25]
        self._loop_bars_options = [1, 2, 4, 8, 16]
        self._loop_bars_index = 0
        # Per-drum buffers (128 notes for full piano roll)
        self._drum_velocity = [64] * 128  # 0-127
        self._drum_pressure = [0] * 128   # 0-127
        self._selected_drum = 0          # index into _row_note_offsets (0..127, full MIDI range)
        # Track last interacted column (from pad presses) to target exact step selection
        self._last_interacted_col = None
        # LED palette indices (APC40 MkII): 21 ~ bright green, 45 ~ blue (per protocol tables)
        self._LED_GREEN = 21
        # Track shift button state internally (is_pressed property unreliable)
        self._shift_is_pressed = False
        # Beat indicator / playhead blink state
        self._last_blink_col = None
        self._blink_on = False
        self._blink_phase = 0  # Track blink phase to prevent rapid toggling
        self._current_tempo = 120.0  # Track current tempo for dynamic tick rate
        self._tick_in_progress = False  # Prevent multiple simultaneous ticks
        # Copy/paste buffer for drum notes
        self._copied_notes = None
        # Define color codes (APC40 MkII LED palette)
        self._LED_RED = 5
        self._LED_YELLOW = 13
        self._LED_ORANGE = 9
        self._LED_BLUE = 79  # Full bright blue for function system
        self._LED_PURPLE = 81
        self._LED_DARK_PURPLE = 82
        self._LED_BROWN = 11
        self._LED_DARK_BROWN = 12
        # Rainbow colors for note length visualization
        self._LED_PINK = 95
        self._LED_CYAN = 37
        self._LED_LIME = 17
        self._LED_WHITE = 3  # White for playhead (matches Ableton's white bar)
        self._rainbow_colors = [self._LED_RED, self._LED_ORANGE, self._LED_YELLOW, self._LED_LIME, 
                                self._LED_GREEN, self._LED_CYAN, self._LED_BLUE, self._LED_PURPLE, self._LED_PINK]
        # Function system: Global function selector and per-drum assignments
        # RED=clear, YELLOW=copy, ORANGE=paste, BLUE=MPE marker, PURPLE=fill 1/4, etc.
        self._function_colors = [0, self._LED_RED, self._LED_YELLOW, self._LED_ORANGE, self._LED_BLUE,
                                  self._LED_PURPLE, self._LED_DARK_PURPLE, self._LED_LIME, self._LED_GREEN]
        self._current_function_color = 0  # 0 = no function selected
        self._drum_functions = {}  # Maps drum_index -> set([function_color, ...]) assignments
        # Track loop position for clip stop button indicator
        self._last_loop_position_page = None
        self._clip_stop_blink_state = False  # Toggle state for blinking
        # Animation state for note length visualization
        self._animation_active = False
        self._animation_counter = 0
        self._animation_start_time = 0.0  # Track when animation started (in beats)
        self._animation_max_duration_beats = 4.0  # Maximum duration in beats
        # Function button blink state (for buttons that can't change color)
        self._function_button_blink_count = 0
        self._function_button_blink_target = 0
        self._function_button_blink_phase = 0
        # Master button blink state for execution feedback
        self._master_button_blink_count = 0
        # Scale awareness for visual guidance (melodic instruments only)
        self._scale_notes = set()  # Set of MIDI notes that are in the current scale
        self._root_note = 0  # Root note of the scale (0-11, C=0)
        self._scale_name = "Major"  # Current scale name
        self._is_drum_rack = False  # Track if current instrument is a drum rack
        self._chromatic_blink_notes = set()  # Notes that became chromatic after scale change
        self._master_button_blink_target = 0
        self._master_button_blink_phase = 0
        # Pending rotation after scene preview
        self._pending_function_rotation = False
        # Initialize copy/paste queues
        self._copy_queue = []
        self._paste_queue = []
        self._copied_multi = []
        # Scene preview flash state (flash scene launch buttons on Stop All)
        self._scene_preview_active = False
        self._scene_preview_color = 0
        self._scene_preview_count = 0
        self._scene_preview_target = 0
        self._scene_preview_phase = 0
        # Store track and scene when entering sequencer to prevent track switching issues
        self._sequencer_track = None
        self._sequencer_scene_index = None
        # Function indicator patterns for Stop All button
        # Each function has a distinct blink count to show current selection
        self._function_indicator_patterns = {
            0: 0,
            self._LED_RED: 1,
            self._LED_YELLOW: 2,
            self._LED_ORANGE: 3,
            self._LED_BLUE: 4,
            self._LED_PURPLE: 5,
            self._LED_DARK_PURPLE: 6,
            self._LED_LIME: 7,
            self._LED_GREEN: 8
        }

        # Register listeners
        try:
            # user/pan/sends handled by APC40_MkII_step
            self._left_button.add_value_listener(self._on_left)
            self._right_button.add_value_listener(self._on_right)
            self._up_button.add_value_listener(self._on_up)
            self._down_button.add_value_listener(self._on_down)
            if self._prev_device_button:
                self._prev_device_button.add_value_listener(self._on_prev_drum)
            if self._next_device_button:
                self._next_device_button.add_value_listener(self._on_next_drum)
            # Scene launch buttons now control drum function selection
            for i, btn in enumerate(self._scene_launch_buttons_raw):
                btn.add_value_listener(lambda value, sender, idx=i: self._on_scene_launch_button(idx, value), identify_sender=True)
            # Stop all clips button cycles through selected drums
            if self._stop_all_button:
                self._stop_all_button.add_value_listener(self._on_stop_all_button)
                try:
                    if self._enable_logging:
                        self._log("StepSequencer: Stop All button listener registered")
                except Exception:
                    pass
            # Master button executes the selected function
            if self._master_button:
                self._master_button.add_value_listener(self._on_master_button)
            for btn in self._clip_stop_buttons_raw:
                btn.add_value_listener(self._on_clip_stop_button, identify_sender=True)
            for row in self._matrix_rows_raw:
                for btn in row:
                    btn.add_value_listener(self._on_matrix_button, identify_sender=True)
            # Assignable knobs (48-55): send MPE Pitch Bend, Shift+knob: send MPE Slide (CC74)
            for i, knob in enumerate(self._knob_controls):
                knob.add_value_listener(lambda value, sender, knob_index=i: self._on_knob_value(knob_index, value, sender), identify_sender=True)
            # Device control knobs (general purpose/CC20-23 etc): set per-drum Pressure/Velocity buffers
            for i, knob in enumerate(self._device_controls):
                knob.add_value_listener(lambda value, sender, knob_index=i: self._on_device_knob_value(knob_index, value, sender), identify_sender=True)
            # Register track select button listeners for note length control
            for i, btn in enumerate(self._track_select_buttons):
                btn.add_value_listener(lambda value, sender, track_index=i: self._on_track_select(track_index, value), identify_sender=True)
            # Listen for shift changes to resync knob LED rings between modes
            if self._shift_button:
                self._shift_button.add_value_listener(self._on_shift_value)
            # Monitor tempo changes for accurate playhead tracking
            if hasattr(self._song, 'tempo') and hasattr(self._song, 'add_tempo_listener'):
                self._song.add_tempo_listener(self._on_tempo_changed)
                # Initialize current tempo
                try:
                    self._current_tempo = float(self._song.tempo)
                except Exception:
                    self._current_tempo = 120.0
            # Initial render of note length LEDs on track select buttons
            try:
                self._render_note_length_leds()
            except Exception:
                pass
        except Exception:
            pass
    
    def _log(self, message):
        """Wrapper for logging that respects the enable_logging flag"""
        if self._enable_logging:
            try:
                self._cs.log_message(message)
            except Exception:
                pass

    def _ensure_copy_paste_queues(self):
        if not hasattr(self, '_copy_queue'):
            self._copy_queue = []
        if not hasattr(self, '_paste_queue'):
            self._paste_queue = []
        if not hasattr(self, '_copied_multi'):
            self._copied_multi = []

    def _on_shift_value(self, value):
        # Momentary shift: pressed when value > 0, otherwise not pressed.
        # Track state internally since is_pressed property is unreliable.
        try:
            self._shift_is_pressed = bool(value)
            try:
                if self._enable_logging:
                    self._log("Shift %s" % ("pressed" if self._shift_is_pressed else "released"))
            except Exception:
                pass
            # Resync knob LED rings to show the correct per-mode buffer immediately
            try:
                self._sync_knob_leds()
            except Exception:
                pass
        except Exception:
            pass

    def _select_current_column_notes(self):
        # Select only the notes in the exact visible step (column) and selected drum
        clip = self._get_cached_clip()
        if clip is None:
            return
        # Determine column priority: last pad press > blinking playhead > 0
        try:
            if getattr(self, '_last_interacted_col', None) is not None:
                col = int(self._last_interacted_col)
            elif getattr(self, '_last_blink_col', None) is not None:
                col = int(self._last_blink_col)
            else:
                col = 0
        except Exception:
            col = 0
        # Compute precise time window for this step
        try:
            step = int(col) + int(self._time_page) * int(self._steps_per_page)
            note_len = float(self._note_lengths[self._note_length_index])
            start = float(step) * note_len
            # Use a tight selection window around the step start to avoid selecting whole row
            from_time = max(0.0, start + 0.000)
            time_span = min(note_len, 0.010)
        except Exception:
            return
        # Pitch (selected drum row)
        try:
            pitch = int(self._row_note_offsets[self._selected_drum])
        except Exception:
            return
        try:
            # Debug: log capability snapshot
            try:
                caps = [
                    ("select_notes_extended", hasattr(clip, 'select_notes_extended')),
                    ("get_notes_extended", hasattr(clip, 'get_notes_extended')),
                    ("apply_note_modifications", hasattr(clip, 'apply_note_modifications')),
                    ("deselect_all_notes", hasattr(clip, 'deselect_all_notes')),
                ]
                if self._enable_logging:
                    self._log("Select window col=%d pitch=%d from=%.5f span=%.5f caps=%s" % (int(col), int(pitch), float(from_time), float(time_span), str(caps)))
            except Exception:
                pass
            # Prefer Live 12 extended selection API if available; select exact notes at this step
            if hasattr(clip, 'get_notes_extended') and hasattr(clip, 'select_notes_extended'):
                # First, find the notes in this step window
                step_notes = clip.get_notes_extended(from_pitch=pitch, pitch_span=1, from_time=from_time, time_span=time_span)
                try:
                    if self._enable_logging:
                        self._log("Found %d notes in step window" % (len(step_notes) if step_notes else 0))
                except Exception:
                    pass
                clip.deselect_all_notes()
                # Select each note precisely using a very small span around its start_time
                for n in step_notes or []:
                    try:
                        sel_time = float(n.start_time)
                        sel_span = max(0.001, min(float(n.duration), 0.010))
                        clip.select_notes_extended(from_time=sel_time, from_pitch=int(n.pitch), time_span=sel_span, pitch_span=1)
                        try:
                            if self._enable_logging:
                                self._log("Selected note pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
                        except Exception:
                            pass
                    except Exception:
                        continue
            else:
                # Fallback: selection API not available; skip broad select to avoid row-wide edits
                try:
                    if self._enable_logging:
                        self._log("select_notes_extended unavailable; skipping selection fallback to avoid selecting entire row")
                except Exception:
                    pass
        except Exception:
            pass
    
    # LED helpers and grid refresh
    def _set_pad_led_color(self, col, row, color_value):
        try:
            btn = self._matrix_rows_raw[row][col]
            try:
                btn.send_value(int(color_value), True)
            except Exception:
                try:
                    # Fallback to generic on/off if color not supported
                    if color_value:
                        btn.set_light("DefaultButton.On")
                    else:
                        btn.set_light("DefaultButton.Off")
                except Exception:
                    try:
                        (btn.turn_on() if color_value else btn.turn_off())
                    except Exception:
                        pass
        except Exception:
            pass

    def _refresh_grid(self):
        # reflect current clip notes on the visible grid
        # Get clip slot but DON'T create a new clip - only show existing notes
        slot = self._current_clip_slot()
        clip = None
        note_count = 0
        
        try:
            if self._enable_logging:
                self._log("=== GRID REFRESH START ===")
                self._log("Note length: %.2f beats (index %d)" % (self._note_lengths[self._note_length_index], self._note_length_index))
                self._log("Time page: %d, Drum base: %d" % (self._time_page, self._drum_row_base))
                self._log("Loop: %d bars = %.1f beats" % (self._loop_bars_options[self._loop_bars_index], self._loop_bars_options[self._loop_bars_index] * 4.0))
        except Exception:
            pass
        
        if slot and slot.has_clip:
            try:
                clip = slot.clip
                try:
                    if self._enable_logging:
                        self._log("Grid refresh - found clip")
                except Exception:
                    pass
            except Exception:
                pass
        
        for r in range(len(self._matrix_rows_raw)):
            for c in range(min(self._steps_per_page, len(self._matrix_rows_raw[r]))):
                # ABLETON LAYOUT: Top row (r=0) = highest visible note, Bottom row (r=4) = lowest
                # Invert row indexing: row_offset = (base + rows_visible - 1) - r
                row_offset = (self._drum_row_base + self._rows_visible - 1) - r
                if row_offset >= len(self._row_note_offsets) or row_offset < 0:
                    self._set_pad_led_color(c, r, 0)
                    continue
                pitch = self._row_note_offsets[row_offset]
                step = c + self._time_page * self._steps_per_page
                note_len = self._note_lengths[self._note_length_index]
                start = step * note_len
                # Use actual clip loop length if available for bounds check
                try:
                    clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                    if clip_loop_len <= 0.0:
                        clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
                except Exception:
                    clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
                if start >= clip_loop_len:
                    self._set_pad_led_color(c, r, 0)
                    continue
                if clip is None:
                    self._set_pad_led_color(c, r, 0)
                    continue
                try:
                    # Use unified helper for robust detection
                    has_note = self._has_note_overlap_at(clip, pitch, float(start), float(note_len))
                    if has_note:
                        note_count += 1
                except Exception as e:
                    has_note = False
                
                # SCALE-AWARE COLOR CODING (melodic instruments only)
                if self._is_drum_rack:
                    # DRUMS: Simple green/blue coloring, no scale awareness
                    if row_offset == self._selected_drum:
                        color = self._LED_GREEN if has_note else self._LED_BLUE
                    else:
                        color = self._LED_GREEN if has_note else 0
                    self._set_pad_led_color(c, r, color)
                else:
                    # MELODIC: Scale-aware coloring with blinking for newly chromatic notes
                    in_scale = pitch in self._scale_notes
                    is_root = (pitch % 12) == (self._root_note % 12)
                    is_newly_chromatic = has_note and pitch in self._chromatic_blink_notes
                    
                    if row_offset == self._selected_drum:
                        # Selected row: always blue when empty, green when has note
                        color = self._LED_GREEN if has_note else self._LED_BLUE
                        self._set_pad_led_color(c, r, color)
                    else:
                        # Other rows: Scale-aware coloring
                        if has_note:
                            if is_newly_chromatic:
                                # Blink newly chromatic notes (alternate ORANGE/OFF)
                                color = self._LED_ORANGE if self._clip_stop_blink_state else 0
                            elif in_scale:
                                # Normal in-scale note
                                color = self._LED_GREEN
                            else:
                                # Chromatic note (was already chromatic)
                                color = self._LED_ORANGE
                        else:
                            # Empty: BLUE (dim) if in scale, OFF if chromatic, CYAN if root
                            if is_root:
                                color = self._LED_CYAN  # Root note indicator
                            elif in_scale:
                                color = self._LED_BLUE  # In-scale note available
                            else:
                                color = 0  # Chromatic note (off)
                        self._set_pad_led_color(c, r, color)
        
        # Log summary after refresh - use try/except for safety
        try:
            if self._enable_logging:
                self._log("Grid refresh complete - found " + str(note_count) + " notes to display")
        except Exception:
            pass
        # Update scene function LEDs to reflect current drum view
        try:
            self._render_scene_function_leds()
        except Exception:
            pass

    def _detect_scale(self, check_for_changes=False):
        """Detect current scale from Ableton and calculate in-scale notes.
        
        Args:
            check_for_changes: If True, detects newly chromatic notes for blinking
        """
        # Skip scale detection for drum racks
        if self._is_drum_rack:
            self._scale_notes = set(range(128))  # All notes valid for drums
            return
        
        try:
            # Store previous scale for change detection
            old_scale_notes = self._scale_notes.copy() if check_for_changes else set()
            old_root = self._root_note
            old_name = self._scale_name
            
            # Read scale info from Live API
            if hasattr(self._song, 'root_note') and hasattr(self._song, 'scale_name'):
                new_root = int(self._song.root_note)  # 0-11, C=0
                new_name = str(self._song.scale_name)
                
                # Check if scale changed
                scale_changed = check_for_changes and (new_root != old_root or new_name != old_name)
                
                if scale_changed:
                    # Calculate new scale
                    new_scale_notes = self._calculate_scale_notes(new_root, new_name)
                    
                    # Find notes that are now chromatic (were in scale, now out of scale)
                    self._chromatic_blink_notes = old_scale_notes - new_scale_notes
                    
                    # Update scale
                    self._root_note = new_root
                    self._scale_name = new_name
                    self._scale_notes = new_scale_notes
                    
                    # Log scale change
                    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
                    root_name = note_names[self._root_note % 12]
                    self._log("SCALE CHANGED: %s %s (%d chromatic notes now)" % (root_name, self._scale_name, len(self._chromatic_blink_notes)))
                elif not check_for_changes:
                    # Initial detection
                    self._root_note = new_root
                    self._scale_name = new_name
                    self._scale_notes = self._calculate_scale_notes(self._root_note, self._scale_name)
                    
                    # Log scale info
                    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
                    root_name = note_names[self._root_note % 12]
                    self._log("Scale: %s %s (%d notes in scale)" % (root_name, self._scale_name, len(self._scale_notes)))
            else:
                # No scale info available - use chromatic (all notes)
                self._scale_notes = set(range(128))
                if not check_for_changes:
                    self._log("Scale: Chromatic (no scale set in Ableton)")
        except Exception as e:
            # Fallback to chromatic
            self._scale_notes = set(range(128))
            if not check_for_changes:
                self._log("Scale detection failed: " + str(e))
    
    def _calculate_scale_notes(self, root, scale_name):
        """Calculate all MIDI notes in the given scale across all octaves."""
        # Scale intervals (semitones from root)
        scale_intervals = {
            'Major': [0, 2, 4, 5, 7, 9, 11],
            'Minor': [0, 2, 3, 5, 7, 8, 10],
            'Dorian': [0, 2, 3, 5, 7, 9, 10],
            'Mixolydian': [0, 2, 4, 5, 7, 9, 10],
            'Lydian': [0, 2, 4, 6, 7, 9, 11],
            'Phrygian': [0, 1, 3, 5, 7, 8, 10],
            'Locrian': [0, 1, 3, 5, 6, 8, 10],
            'Diminished': [0, 2, 3, 5, 6, 8, 9, 11],
            'Whole Tone': [0, 2, 4, 6, 8, 10],
            'Whole-Half': [0, 2, 3, 5, 6, 8, 9, 11],
            'Half-Whole': [0, 1, 3, 4, 6, 7, 9, 10],
            'Harmonic Minor': [0, 2, 3, 5, 7, 8, 11],
            'Melodic Minor': [0, 2, 3, 5, 7, 9, 11],
            'Super Locrian': [0, 1, 3, 4, 6, 8, 10],
            'Bhairav': [0, 1, 4, 5, 7, 8, 11],
            'Hungarian Minor': [0, 2, 3, 6, 7, 8, 11],
            'Minor Blues': [0, 3, 5, 6, 7, 10],
            'Major Blues': [0, 2, 3, 4, 7, 9],
            'Minor Pentatonic': [0, 3, 5, 7, 10],
            'Major Pentatonic': [0, 2, 4, 7, 9],
            'Spanish': [0, 1, 4, 5, 7, 8, 10],
            'Gypsy': [0, 2, 3, 6, 7, 8, 11],
            'Arabian': [0, 2, 4, 5, 6, 8, 10],
            'Flamenco': [0, 1, 4, 5, 7, 8, 11],
            'Japanese': [0, 1, 5, 7, 8],
            'Egyptian': [0, 2, 5, 7, 10],
            'Blues': [0, 3, 5, 6, 7, 10],
            'Chromatic': list(range(12))  # All notes
        }
        
        # Get intervals for this scale (default to Major if unknown)
        intervals = scale_intervals.get(scale_name, scale_intervals['Major'])
        
        # Generate all notes in scale across all MIDI range (0-127)
        notes = set()
        for octave in range(11):  # MIDI has ~10 octaves
            for interval in intervals:
                note = root + (octave * 12) + interval
                if 0 <= note <= 127:
                    notes.add(note)
        
        return notes
    
    def _enter(self):
        self._mode = True
        # Store the current track and scene so all operations work on the same clip
        # even if the user switches views during sequencer mode
        try:
            self._sequencer_track = self._song.view.selected_track
            self._sequencer_scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
            try:
                track_name = self._sequencer_track.name if hasattr(self._sequencer_track, 'name') else 'Unknown'
                self._log("Sequencer locked to Track='%s' Scene=%d" % (track_name, self._sequencer_scene_index))
            except Exception:
                pass
        except Exception as e:
            try:
                self._log("WARNING: Could not lock track/scene: " + str(e))
            except Exception:
                pass
        
        # DYNAMIC SEQUENCER: Detect instrument type and configure note range
        try:
            is_drum_rack = False
            drum_rack_device = None
            
            if self._sequencer_track and hasattr(self._sequencer_track, 'devices'):
                for device in self._sequencer_track.devices:
                    if hasattr(device, 'can_have_drum_pads') and device.can_have_drum_pads:
                        is_drum_rack = True
                        drum_rack_device = device
                        break
                    # Also check device name for "Drum" as fallback
                    if hasattr(device, 'name') and 'Drum' in device.name:
                        is_drum_rack = True
                        drum_rack_device = device
                        break
            
            # Store drum rack status for scale coloring decision
            self._is_drum_rack = is_drum_rack
            
            if is_drum_rack and drum_rack_device:
                # DRUM RACK: Detect loaded drum pads only (those with samples/names)
                loaded_pads = []
                try:
                    if hasattr(drum_rack_device, 'drum_pads'):
                        for pad in drum_rack_device.drum_pads:
                            if pad and hasattr(pad, 'note') and hasattr(pad, 'chains'):
                                # Pad is loaded if it has chains (devices)
                                if len(pad.chains) > 0:
                                    loaded_pads.append(int(pad.note))
                    
                    if loaded_pads:
                        # Use only loaded pads, sorted low to high
                        loaded_pads.sort()
                        self._row_note_offsets = loaded_pads
                        # Resize buffers to match number of loaded pads
                        num_pads = len(loaded_pads)
                        self._drum_velocity = [64] * num_pads
                        self._drum_pressure = [0] * num_pads
                        # Start at beginning (lowest loaded pad at bottom of grid)
                        self._drum_row_base = 0
                        self._log("Drum Rack: Found %d loaded pads (notes %d-%d)" % (num_pads, loaded_pads[0], loaded_pads[-1]))
                        self._log("Grid Layout: TOP ROW = Note %d, BOTTOM ROW = Note %d (matches Ableton)" % (loaded_pads[min(4, num_pads-1)], loaded_pads[0]))
                    else:
                        # No pads detected, use standard drum range (36-51)
                        self._row_note_offsets = list(range(36, 52))  # C1 to D#2
                        self._drum_velocity = [64] * 16
                        self._drum_pressure = [0] * 16
                        self._drum_row_base = 0
                        self._log("Drum Rack: No pads detected, using standard range (C1-D#2)")
                except Exception as e:
                    # Fallback to standard drum range
                    self._row_note_offsets = list(range(36, 52))
                    self._drum_velocity = [64] * 16
                    self._drum_pressure = [0] * 16
                    self._drum_row_base = 0
                    self._log("Drum Rack pad detection failed: " + str(e))
            else:
                # MELODIC INSTRUMENT: Full chromatic range, start at middle C
                self._row_note_offsets = list(range(128))  # Full MIDI range
                # Keep 128-note buffers for melodic instruments (don't resize)
                # Buffers already initialized to 128 in __init__
                self._drum_row_base = 48  # Start at C3 (middle C area)
                self._log("Melodic instrument: Full range (0-127), starting at C3 (note 48)")
                self._log("Grid Layout: TOP ROW = Note 52 (E3), BOTTOM ROW = Note 48 (C3)")
        except Exception as e:
            # Fallback to melodic mode with middle C start
            self._row_note_offsets = list(range(128))
            # Keep 128-note buffers (already initialized)
            self._drum_row_base = 48
            try:
                self._log("Instrument detection error: " + str(e))
            except Exception:
                pass
        
        # Check if clip has any notes - if not, initialize to default settings
        try:
            slot = self._current_clip_slot()
            has_any_notes = False
            if slot and slot.has_clip:
                try:
                    clip = slot.clip
                    # Check if clip has any notes
                    if hasattr(clip, 'get_notes_extended'):
                        # Check entire clip for any notes
                        all_notes = clip.get_notes_extended(0, 128, 0.0, 9999.0)
                        has_any_notes = bool(all_notes and len(all_notes) > 0)
                    elif hasattr(clip, 'get_notes'):
                        # Fallback to old API
                        all_notes = clip.get_notes(0.0, 0, 9999.0, 128)
                        has_any_notes = bool(all_notes and len(all_notes) > 0)
                except Exception:
                    has_any_notes = False
            
            # If no notes exist, initialize to 1 bar with 1/4 note resolution
            if not has_any_notes:
                self._loop_bars_index = 0  # 1 bar
                self._note_length_index = 5  # 1/4 bar (1.0 beats)
                try:
                    if self._enable_logging:
                        self._log("No notes detected - initializing to 1 bar, 1/4 note resolution")
                except Exception:
                    pass
                # CRITICAL: Actually apply the 1 bar loop to the clip so it doesn't play forever
                try:
                    self._apply_loop_length()
                    if self._enable_logging:
                        self._log("Applied 1 bar loop length to blank clip")
                except Exception as e:
                    try:
                        if self._enable_logging:
                            self._log("Failed to apply loop length to blank clip: " + str(e))
                    except Exception:
                        pass
        except Exception as e:
            try:
                if self._enable_logging:
                    self._log("Note detection error: " + str(e))
            except Exception:
                pass
        
        # Update current tempo on entry for immediate accuracy
        try:
            if hasattr(self._song, 'tempo'):
                self._current_tempo = float(self._song.tempo)
        except Exception:
            pass
        
        # PERFORMANCE: Cache the clip reference on entry
        self._invalidate_clip_cache()
        self._get_cached_clip()
        
        # SCALE AWARENESS: Detect and calculate scale notes for visual guidance
        try:
            self._detect_scale()
        except Exception as e:
            try:
                self._log("Scale detection error: " + str(e))
            except Exception:
                pass
        
        # Log sequencer state for debugging
        try:
            if self._enable_logging:
                self._log("=== Sequencer Enter ===")
                self._log("Tempo: %.1f BPM" % self._current_tempo)
                self._log("time_page: " + str(self._time_page) + " drum_row_base: " + str(self._drum_row_base))
                self._log("note_length_index: " + str(self._note_length_index) + " loop_bars_index: " + str(self._loop_bars_index))
            if self._enable_logging:
                # Calculate and log the tick interval
                tick_interval = self._calculate_tick_interval()
                update_rate_ms = tick_interval * 30
                self._log("Playhead update rate: every %d ticks (~%dms) for %.1f BPM" % (tick_interval, update_rate_ms, self._current_tempo))
                slot = self._current_clip_slot()
                if slot:
                    self._log("Clip slot found - has_clip: " + str(slot.has_clip))
                    if slot.has_clip:
                        try:
                            clip = slot.clip
                            # Log which clip we're viewing
                            try:
                                track_name = self._song.view.selected_track.name if hasattr(self._song.view.selected_track, 'name') else 'Unknown'
                                scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
                                clip_name = clip.name if hasattr(clip, 'name') else 'Unnamed'
                                self._log("Viewing clip: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
                            except Exception:
                                pass
                            self._log("Clip is_midi_clip: " + str(clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else 'N/A'))
                        except Exception as e:
                            self._log("Error accessing clip: " + str(e))
                else:
                    self._log("No clip slot found")
        except Exception as e:
            try:
                if self._enable_logging:
                    self._log("Sequencer enter logging error: " + str(e))
            except Exception:
                pass
        # Sync knob LEDs to current buffer values when entering
        try:
            self._sync_knob_leds()
        except Exception:
            pass
        # Render scene function LEDs
        try:
            self._render_scene_function_leds()
        except Exception:
            pass
        # Ensure Stop All and Master buttons are OFF by default; they only blink for feedback
        try:
            if self._stop_all_button:
                self._stop_all_button.send_value(0, True)
        except Exception:
            pass
        try:
            if self._master_button:
                self._master_button.send_value(0, True)
        except Exception:
            pass
        # Render note length button LEDs
        try:
            self._render_note_length_leds()
        except Exception:
            pass
        # CRITICAL: Refresh grid to show the current clip's notes (not previous clip)
        try:
            self._log("Refreshing grid for current clip...")
            self._refresh_grid()
        except Exception as e:
            try:
                self._log("Grid refresh on enter failed: " + str(e))
            except Exception:
                pass
        # CRITICAL: Start playhead tracking by scheduling first tick
        try:
            self._schedule_tick()
            self._log("Playhead tracking started")
        except Exception as e:
            try:
                self._log("Failed to start playhead tracking: " + str(e))
            except Exception:
                pass
    
    def _exit(self):
        self._mode = False
        # CRITICAL: Stop playhead tracking immediately by setting mode to False
        # The _tick() method will see this and stop scheduling itself
        
        # CRITICAL: Clear all LEDs to prevent carryover to next session
        try:
            self._log("Clearing all LEDs on exit...")
            self._clear_all_leds()
        except Exception:
            pass
        # Clear note length LEDs
        try:
            self._clear_note_length_leds()
        except Exception:
            pass
        # Reset state variables to defaults for fresh start next time
        try:
            self._time_page = 0
            self._drum_row_base = 0
            self._last_interacted_col = None
            self._last_blink_col = None
            self._blink_phase = 0
            self._last_loop_position_page = None
            self._clip_stop_blink_state = False
            self._animation_active = False
            self._animation_counter = 0
            self._animation_start_time = 0.0
            self._function_button_blink_count = 0
            self._function_button_blink_target = 0
            self._function_button_blink_phase = 0
            self._master_button_blink_count = 0
            self._master_button_blink_target = 0
            self._master_button_blink_phase = 0
            # Clear track/scene lock
            self._sequencer_track = None
            self._sequencer_scene_index = None
            # Clear copied notes buffer
            self._copied_notes = None
            # Clear function assignments
            self._drum_functions = {}
            self._current_function_color = 0
            # Clear any queues
            self._copy_queue = []
            self._paste_queue = []
            self._copied_multi = []
            # Reset tick guard
            self._tick_in_progress = False
            self._log("State variables reset to defaults (track/scene unlocked, buffers cleared)")
        except Exception:
            pass
        # Clear clip stop button LEDs (loop position indicators)
        try:
            for btn in self._clip_stop_buttons_raw:
                try:
                    btn.send_value(0, True)
                except Exception:
                    pass
        except Exception:
            pass
        # Clear function selector buttons
        try:
            if self._stop_all_button:
                self._stop_all_button.send_value(0, True)
        except Exception:
            pass
        try:
            if self._master_button:
                self._master_button.send_value(0, True)
        except Exception:
            pass
    
    def _clear_note_length_leds(self):
        # Turn off all note length button LEDs
        try:
            for btn in self._track_select_buttons:
                try:
                    btn.set_light("DefaultButton.Off")
                except Exception:
                    try:
                        btn.turn_off()
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_left(self, value):
        if not value or not self._mode:
            return
        if self._time_page > 0:
            self._time_page -= 1
            try:
                self._log("Left pressed - time_page now: " + str(self._time_page))
            except Exception:
                pass
            self._refresh_grid()

    def _on_right(self, value):
        if not value or not self._mode:
            return
        # Calculate maximum page based on loop length and note length
        try:
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0  # in beats
            note_len = self._note_lengths[self._note_length_index]
            total_steps = int(loop_length / note_len)
            max_page = max(0, (total_steps - 1) // self._steps_per_page)
            
            if self._time_page < max_page:
                self._time_page += 1
                try:
                    if self._enable_logging:
                        self._log("Right pressed - time_page now: %d (max: %d)" % (self._time_page, max_page))
                except Exception:
                    pass
            else:
                try:
                    if self._enable_logging:
                        self._log("Already at end of loop (page %d of %d)" % (self._time_page, max_page))
                except Exception:
                    pass
        except Exception:
            # Fallback: allow navigation but log error
            self._time_page += 1
            try:
                if self._enable_logging:
                    self._log("Right pressed (fallback) - time_page now: " + str(self._time_page))
            except Exception:
                pass
        self._refresh_grid()

    def _on_up(self, value):
        if not value or not self._mode:
            return
        # UP = Navigate to HIGHER notes (increase base)
        max_base = max(0, len(self._row_note_offsets) - self._rows_visible)
        if self._drum_row_base < max_base:
            self._drum_row_base += 1
            try:
                # Show which notes are now visible (top to bottom)
                top_idx = min(self._drum_row_base + self._rows_visible - 1, len(self._row_note_offsets) - 1)
                bottom_idx = self._drum_row_base
                top_note = self._row_note_offsets[top_idx]
                bottom_note = self._row_note_offsets[bottom_idx]
                self._log("Up: base=%d, TOP ROW=note %d, BOTTOM ROW=note %d" % (self._drum_row_base, top_note, bottom_note))
            except Exception:
                pass
            self._refresh_grid()
        else:
            try:
                self._log("Up: Already at highest notes (base=%d, max=%d)" % (self._drum_row_base, max_base))
            except Exception:
                pass

    def _on_down(self, value):
        if not value or not self._mode:
            return
        # DOWN = Navigate to LOWER notes (decrease base)
        if self._drum_row_base > 0:
            self._drum_row_base -= 1
            try:
                # Show which notes are now visible (top to bottom)
                top_idx = min(self._drum_row_base + self._rows_visible - 1, len(self._row_note_offsets) - 1)
                bottom_idx = self._drum_row_base
                top_note = self._row_note_offsets[top_idx]
                bottom_note = self._row_note_offsets[bottom_idx]
                self._log("Down: base=%d, TOP ROW=note %d, BOTTOM ROW=note %d" % (self._drum_row_base, top_note, bottom_note))
            except Exception:
                pass
            self._refresh_grid()
        else:
            try:
                self._log("Down: Already at lowest notes (base=0)")
            except Exception:
                pass
    def _on_knob_value(self, knob_index, value, sender=None):
        if not self._mode:
            return
        # Use internal shift state tracking instead of is_pressed property
        shift_pressed = getattr(self, '_shift_is_pressed', False)
        # Logging disabled for performance (called frequently)
        if shift_pressed:
            for ch in self._mpe_channels:
                try:
                    self._cs._send_midi((0xB0 | ch, 74, int(value)))
                except Exception:
                    pass
        else:
            v14 = max(0, min(16383, int(round((value / 127.0) * 16383))))
            lsb = v14 & 0x7F
            msb = (v14 >> 7) & 0x7F
            for ch in self._mpe_channels:
                try:
                    self._cs._send_midi((0xE0 | ch, lsb, msb))
                except Exception:
                    pass
            # Store last Pitch Bend proxy value (7-bit for ring) in Pitch mode
            try:
                if 0 <= knob_index < len(self._assignable_knob_pitch_values):
                    self._assignable_knob_pitch_values[knob_index] = int(value)
            except Exception:
                pass
        # Keep clip note selection synced to current column for MPE editing
        try:
            self._select_current_column_notes()
        except Exception:
            pass
        # Light the ring LED (if present)
        try:
            if sender is not None and hasattr(sender, 'send_value'):
                sender.send_value(int(value), True)
        except Exception:
            pass
        # Directly light APC40 MkII assignable knob ring via CC 56-63 on channel 0
        try:
            ring_cc = 56 + int(knob_index)
            val = max(0, min(127, int(value)))
            self._cs._send_midi((0xB0 | 0, ring_cc, val))
        except Exception:
            pass
        # Also update all related knob LEDs to reflect buffers for selected drum
        try:
            self._sync_knob_leds()
        except Exception:
            pass

    def _on_device_knob_value(self, knob_index, value, sender=None):
        if not self._mode:
            return
        # Without shift: set MPE pressure buffer for selected drum
        # With shift: set velocity buffer for selected drum
        # Use internal shift state tracking instead of is_pressed property
        shift_pressed = getattr(self, '_shift_is_pressed', False)
        idx = max(0, min(len(self._drum_velocity) - 1, int(self._selected_drum)))
        # Debug: log device knob intent
        try:
            self._log("Device knob %d value=%d target=%s drum=%d" % (int(knob_index), int(value), ("Velocity" if shift_pressed else "Pressure(release_velocity)"), int(idx)))
        except Exception:
            pass
        # Compute current step window so we only update notes in the visible step
        try:
            pitch, from_time, time_span = self._current_step_window()
        except Exception:
            pitch = None
            from_time = None
            time_span = None
        if shift_pressed:
            # Safety check: ensure index is within buffer bounds
            if idx < len(self._drum_velocity):
                self._drum_velocity[idx] = int(value)
            # Update existing notes' velocity for the current step (or whole row if window unknown)
            try:
                if pitch is not None:
                    self._update_step_notes(pitch=pitch, from_time=from_time, time_span=time_span, velocity=int(value))
                else:
                    self._update_selected_drum_notes(velocity=int(value))
            except Exception:
                pass
        else:
            # Safety check: ensure index is within buffer bounds
            if idx < len(self._drum_pressure):
                self._drum_pressure[idx] = int(value)
            # Update existing notes' release_velocity (pressure proxy) for the current step
            try:
                if pitch is not None:
                    self._update_step_notes(pitch=pitch, from_time=from_time, time_span=time_span, release_velocity=int(value))
                else:
                    self._update_selected_drum_notes(release_velocity=int(value))
            except Exception:
                pass
        # Update the touched ring encoder LED to reflect current value
        try:
            if sender is not None and hasattr(sender, 'send_value'):
                sender.send_value(int(value), True)
        except Exception:
            pass
        # Directly light APC40 MkII device knob ring via CC 24-31 on channel 0
        try:
            ring_cc = 24 + int(knob_index)
            val = max(0, min(127, int(value)))
            self._cs._send_midi((0xB0 | 0, ring_cc, val))
        except Exception:
            pass
        # Resync all knob LEDs so mode change is reflected immediately
        try:
            self._sync_knob_leds()
        except Exception:
            pass
        # Keep clip note selection synced to current column for piano roll edits
        try:
            self._select_current_column_notes()
        except Exception:
            pass

    def _on_track_select(self, track_index, value):
        if not value or not self._mode:
            return

        # Track select buttons control note length (same as scene buttons)
        if 0 <= track_index < len(self._note_lengths):
            old_index = self._note_length_index
            old_length = self._note_lengths[old_index] if old_index < len(self._note_lengths) else 0
            self._note_length_index = track_index
            new_length = self._note_lengths[track_index]
            try:
                self._log("=== NOTE LENGTH CHANGE ===")
                self._log("Track button %d pressed" % track_index)
                self._log("Old: index=%d length=%.2f beats" % (old_index, old_length))
                self._log("New: index=%d length=%.2f beats" % (track_index, new_length))
                self._log("Mode active: %s" % str(self._mode))
            except Exception:
                pass
            # Update LEDs to reflect the current selection
            try:
                self._render_note_length_leds()
            except Exception:
                pass
            # Trigger rainbow animation to show note length coverage
            try:
                self._trigger_note_length_animation()
            except Exception:
                pass
            # CRITICAL: Reset playhead state when note length changes to prevent performance issues
            try:
                self._last_blink_col = None
                self._blink_phase = 0
                # Invalidate clip cache since we may need fresh clip state
                self._invalidate_clip_cache()
            except Exception:
                pass
            # Refresh grid to show notes at new step size
            try:
                if self._enable_logging:
                    self._log("Refreshing grid after note length change...")
                self._refresh_grid()
                if self._enable_logging:
                    self._log("Grid refresh completed")
            except Exception as e:
                try:
                    if self._enable_logging:
                        self._log("Grid refresh error: " + str(e))
                except Exception:
                    pass

    def _clear_all_leds(self):
        # turn off all 8x5 pad LEDs
        try:
            for r in range(len(self._matrix_rows_raw)):
                row = self._matrix_rows_raw[r]
                for c in range(len(row)):
                    try:
                        row[c].send_value(0, True)
                    except Exception:
                        try:
                            row[c].set_light("DefaultButton.Off")
                        except Exception:
                            try:
                                row[c].turn_off()
                            except Exception:
                                pass
        except Exception:
            pass
        # turn off scene launch LEDs
        try:
            for btn in self._scene_launch_buttons_raw:
                try:
                    btn.send_value(0, True)
                except Exception:
                    try:
                        btn.set_light("DefaultButton.Off")
                    except Exception:
                        try:
                            btn.turn_off()
                        except Exception:
                            pass
        except Exception:
            pass

    # Clip stop buttons: loop bars, with Shift for extended range
    def _on_clip_stop_button(self, value, sender=None):
        if not value or not self._mode:
            return
        if sender not in getattr(self, '_clip_stop_buttons_raw', []):
            return
        index = self._clip_stop_buttons_raw.index(sender)
        # Use internal shift state tracking instead of is_pressed property
        shift_pressed = getattr(self, '_shift_is_pressed', False)

        # Loop length: 1-8 bars on no shift, 9-16 on shift
        options = [1, 2, 4, 8] if not shift_pressed else [9, 10, 12, 16]
        if 0 <= index < len(options):
            temp_options = self._loop_bars_options
            self._loop_bars_options = options
            self._loop_bars_index = index
            try:
                self._log("Loop length changed to " + str(options[index]) + " bars" + (" (shift mode)" if shift_pressed else ""))
            except Exception:
                pass
            self._apply_loop_length()
            self._loop_bars_options = temp_options
            # Reset navigation if we're now beyond the loop
            try:
                loop_length = options[index] * 4.0
                note_len = self._note_lengths[self._note_length_index]
                total_steps = int(loop_length / note_len)
                max_page = max(0, (total_steps - 1) // self._steps_per_page)
                if self._time_page > max_page:
                    self._time_page = 0
                    self._log("Reset time_page to 0 (was beyond new loop length)")
            except Exception:
                pass
            # Force playhead column change on next tick by invalidating cached value
            try:
                # Set to impossible value so next tick forces redraw
                self._last_blink_col = -1
                # Invalidate clip cache since loop length changed
                self._invalidate_clip_cache()
                self._log("Playhead will update on next tick for new loop length")
            except Exception:
                pass
            # Refresh grid to show new loop boundaries
            try:
                self._refresh_grid()
            except Exception:
                pass


    def _render_note_length_leds(self):
        # Light the selected note length button in orange, others off
        try:
            for i, btn in enumerate(self._track_select_buttons):
                try:
                    if i == self._note_length_index:
                        try:
                            btn.set_light("DefaultButton.Alert")
                        except Exception:
                            btn.turn_on()
                    else:
                        try:
                            btn.set_light("DefaultButton.Off")
                        except Exception:
                            btn.turn_off()
                except Exception:
                    continue
        except Exception:
            pass

    def _get_cached_clip(self):
        """Get clip reference with caching for performance. Only calls _ensure_clip() when cache is invalid."""
        if not self._clip_cache_valid or self._cached_clip is None:
            try:
                self._cached_clip = self._ensure_clip()
                self._clip_cache_valid = True
            except Exception:
                self._cached_clip = None
                self._clip_cache_valid = False
        return self._cached_clip
    
    def _invalidate_clip_cache(self):
        """Mark clip cache as invalid so next access will refresh it."""
        self._clip_cache_valid = False

    def _apply_loop_length(self):
        # Apply the selected loop length to the current MIDI clip loop, and also set arrangement loop
        bars = 1
        try:
            bars = int(self._loop_bars_options[self._loop_bars_index])
        except Exception:
            bars = 1
        beats = float(bars) * 4.0
        clip = None
        try:
            clip = self._ensure_clip()
        except Exception:
            clip = None
        # Update clip loop (Session)
        try:
            if clip is not None and hasattr(clip, 'loop_start') and hasattr(clip, 'loop_end'):
                # Quantize loop_start to bar to avoid drift, unless clip already set
                start = float(clip.loop_start)
                try:
                    # If start is not on a bar boundary, snap down to nearest bar
                    snapped = int(start // 4) * 4.0
                    start = snapped
                except Exception:
                    pass
                clip.loop_start = start
                clip.loop_end = start + beats
                clip.looping = True
                # Keep the clip detail visible and show the new loop in the UI
                try:
                    self._ensure_clip_detail_visible(clip)
                    if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                        clip.view.show_loop()
                except Exception:
                    pass
                try:
                    if self._enable_logging:
                        self._log("Applied clip loop: start=%.2f end=%.2f (bars=%d)" % (start, start + beats, bars))
                except Exception:
                    pass
        except Exception:
            pass
        # Also reflect in arrangement loop as a visual cue if desired
        try:
            song = self._song
            if hasattr(song, 'loop_start') and hasattr(song, 'loop_length'):
                # Keep arrangement loop start aligned to clip loop_start if possible
                if clip is not None and hasattr(clip, 'loop_start'):
                    song.loop_start = float(clip.loop_start)
                song.loop_length = beats
                song.loop = True if hasattr(song, 'loop') else True
                try:
                    if self._enable_logging:
                        self._log("Applied arrangement loop: start=%.2f length=%.2f" % (float(song.loop_start), float(song.loop_length)))
                except Exception:
                    pass
        except Exception:
            pass

    # Matrix buttons: toggle notes
    def _on_matrix_button(self, value, sender=None):
        if not value or not self._mode:
            return
        pos = self._locate_matrix_button(sender)
        if pos is None:
            return
        col, row = pos
        # Exit rainbow animation immediately if grid button pressed
        if self._animation_active:
            try:
                self._animation_active = False
                self._animation_counter = 0
                self._log("Rainbow animation cancelled by grid button press")
                # Refresh will happen after note is added/removed below
            except Exception:
                pass
        
        # remember the last step interacted with for precise selection
        try:
            self._last_interacted_col = int(col)
        except Exception:
            pass
        # All rows are now available for note input
        # ABLETON LAYOUT: Top row (r=0) = highest note, Bottom row = lowest note
        row_offset = (self._drum_row_base + self._rows_visible - 1) - row
        if row_offset >= len(self._row_note_offsets) or row_offset < 0:
            return
        pitch = self._row_note_offsets[row_offset]
        step = col + self._time_page * self._steps_per_page
        clip = self._get_cached_clip()
        if clip is None:
            return
        note_len = self._note_lengths[self._note_length_index]
        start = step * note_len
        loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
        # Align to clip's loop start for absolute time operations
        try:
            loop_start = float(getattr(clip, 'loop_start', 0.0))
        except Exception:
            loop_start = 0.0
        if start >= loop_length:
            return
        # Check for existing notes - use precise search window for EXACT step
        # Use very tight tolerance to avoid detecting notes from adjacent steps
        try:
            # Detect notes anchored to the step start only (not entire step window)
            # Small symmetric window around start avoids catching next step
            tolerance = 0.001
            search_start = max(0.0, float(loop_start) + float(start) - tolerance)
            search_duration = max(tolerance * 2, 0.001)
            
            # Use Live 11 API if available, fallback to old API
            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(pitch, 1, search_start, search_duration)
            else:
                # Old API: get_notes(from_time, from_pitch, time_span, pitch_span)
                existing = clip.get_notes(search_start, pitch, search_duration, 1)
            try:
                self._log("=== MATRIX BUTTON PRESSED ===")
                # Log which clip is being modified
                try:
                    track_name = self._song.view.selected_track.name if hasattr(self._song.view.selected_track, 'name') else 'Unknown'
                    scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
                    clip_name = clip.name if hasattr(clip, 'name') else 'Unnamed'
                    self._log("Target: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
                except Exception:
                    pass
                self._log("Position: col=%d row=%d" % (col, row))
                self._log("Pitch: %d, Step: %d" % (pitch, step))
                self._log("Note length: %.2f beats (index %d)" % (note_len, self._note_length_index))
                self._log("Start: %.6f, Search: %.6f-%.6f" % (start, search_start, search_start + search_duration))
                self._log("Found: %d notes" % (len(existing) if existing else 0))
                if existing and len(existing) > 0:
                    self._log("  First note: " + str(existing[0]))
            except Exception:
                pass
        except Exception as e:
            existing = []
            try:
                self._log("get_notes error: " + str(e))
            except Exception:
                pass
        if existing and len(existing) > 0:
            # Remove note
            removed = False
            try:
                found_note = existing[0]
                # Live 11 returns MidiNote objects, old API returns tuples
                if hasattr(found_note, 'pitch'):
                    # MidiNote object from get_notes_extended
                    note_pitch = found_note.pitch
                    note_time = found_note.start_time
                    note_duration = found_note.duration
                else:
                    # Tuple from old get_notes
                    note_pitch = found_note[0]
                    note_time = found_note[1]
                    note_duration = found_note[2]
                
                try:
                    if self._enable_logging:
                        self._log("Removing note - pitch: " + str(note_pitch) + " time: " + str(note_time) + " duration: " + str(note_duration))
                except Exception:
                    pass
                
                # Use Live 11 API if available
                if hasattr(clip, 'remove_notes_extended'):
                    # remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
                    clip.remove_notes_extended(note_pitch, 1, note_time, note_duration)
                else:
                    # Old API: remove_notes(from_time, from_pitch, time_span, pitch_span)
                    clip.remove_notes(note_time, note_pitch, note_duration, 1)
                # Immediate LED feedback: selected row empty -> blue; others -> off
                try:
                    # ABLETON LAYOUT: Use inverted row indexing
                    row_offset = (self._drum_row_base + self._rows_visible - 1) - row
                    if row_offset == self._selected_drum:
                        self._set_pad_led_color(col, row, self._LED_BLUE)
                        try:
                            if sender is not None and hasattr(sender, 'send_value'):
                                sender.send_value(int(self._LED_BLUE), True)
                        except Exception:
                            pass
                    else:
                        self._set_pad_led_color(col, row, 0)
                        try:
                            if sender is not None and hasattr(sender, 'send_value'):
                                sender.send_value(0, True)
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception as e:
                try:
                    if self._enable_logging:
                        self._log("Remove failed: " + str(e))
                except Exception:
                    pass
            # Do not force turn-off here; pad state already updated above
        else:
            # Add note with per-drum velocity/pressure buffers
            drum_index = row_offset
            # Safety check: ensure index is within buffer bounds
            if drum_index >= len(self._drum_velocity) or drum_index >= len(self._drum_pressure):
                velocity = 64  # Default velocity
                mpe_pressure = 0  # Default pressure
            else:
                velocity = int(self._drum_velocity[drum_index])
                mpe_pressure = int(self._drum_pressure[drum_index])
            # Clip note duration if it would extend beyond loop end
            actual_note_len = note_len
            if start + note_len > loop_length:
                actual_note_len = max(0.01, loop_length - start)  # Minimum 0.01 beat duration
                try:
                    if self._enable_logging:
                        self._log("Note clipped: original len=%.2f, clipped to %.2f (loop end at %.2f)" % (note_len, actual_note_len, loop_length))
                except Exception:
                    pass
            try:
                # Write the note using supported APIs (Lite may not support per-note expressions)
                if hasattr(clip, 'add_new_notes'):
                    note_spec = Live.Clip.MidiNoteSpecification(pitch=int(pitch), start_time=float(loop_start) + float(start), duration=float(actual_note_len), velocity=int(velocity), mute=False, release_velocity=int(mpe_pressure))
                    clip.add_new_notes((note_spec,))
                else:
                    # Fallback to legacy API if necessary
                    clip.set_notes(((float(loop_start) + float(start), int(pitch), float(actual_note_len), int(velocity), False),))
                self._log("Note added - pitch: " + str(pitch) + " time: " + str(start) + " duration: " + str(actual_note_len) + " velocity: " + str(velocity) + " mpe: " + str(mpe_pressure))
            except Exception as e:
                try:
                    if self._enable_logging:
                        self._log("Note add failed (fallback): " + str(e))
                except Exception:
                    pass
            # Immediate LED feedback: selected row -> green, others -> green (note exists)
            try:
                self._set_pad_led_color(col, row, self._LED_GREEN)
            except Exception:
                pass
            # Also update sender LED for older fallback
            try:
                sender.send_value(self._LED_GREEN, True)
            except Exception:
                try:
                    sender.set_light("DefaultButton.On")
                except Exception:
                    try:
                        sender.turn_on()
                    except Exception:
                        pass

    # Helpers
    def _select_drum(self, new_index):
        try:
            self._selected_drum = max(0, min(15, int(new_index)))
            self._log("Selected drum index: " + str(self._selected_drum))
        except Exception:
            self._selected_drum = max(0, min(15, int(new_index)))
        # Refresh grid so selected row LEDs change color (blue) and previous row reverts (green)
        try:
            self._refresh_grid()
        except Exception:
            pass
        # Update knob LEDs to reflect selected drum buffers
        try:
            self._sync_knob_leds()
        except Exception:
            pass

    def _render_scene_function_leds(self):
        try:
            assignments_found = 0
            for i, btn in enumerate(self._scene_launch_buttons_raw):
                # ABLETON LAYOUT: Scene buttons map to rows, need inverted indexing
                # Button 0 (top) = highest visible note, Button 4 (bottom) = lowest visible note
                drum_index = (self._drum_row_base + self._rows_visible - 1) - i
                color = 0
                if 0 <= drum_index < len(self._row_note_offsets):
                    if drum_index in self._drum_functions:
                        try:
                            assigned = self._drum_functions[drum_index]
                            if isinstance(assigned, (set, list, tuple)):
                                # If legacy set exists, display a stable member (smallest)
                                color = int(min(assigned)) if len(assigned) > 0 else 0
                            else:
                                # Single int assignment per drum
                                color = int(assigned)
                            if color > 0:
                                assignments_found += 1
                                self._log("Scene button %d (drum %d): showing function color %d" % (i, drum_index, color))
                        except Exception:
                            color = 0
                try:
                    btn.send_value(color, True)
                except Exception:
                    pass
            if assignments_found == 0:
                self._log("No drum function assignments found - all scene buttons turned off")
            else:
                self._log("Rendered %d drum function assignments on scene buttons" % assignments_found)
        except Exception as e:
            self._log("Error in _render_scene_function_leds: %s" % str(e))

    def _ensure_clip_detail_visible(self, clip):
        try:
            # Only set detail clip without forcing view changes
            self._song.view.detail_clip = clip
        except Exception:
            pass

    def _on_shift_value(self, value):
        # When shift state toggles, resync ring LEDs to show appropriate mode data
        try:
            self._sync_knob_leds()
        except Exception:
            pass

    def _on_prev_drum(self, value):
        if not value or not self._mode:
            return
        self._select_drum(self._selected_drum - 1)

    def _on_next_drum(self, value):
        if not value or not self._mode:
            return
        self._select_drum(self._selected_drum + 1)
    def _locate_matrix_button(self, sender):
        if sender is None:
            return None
        for r, row in enumerate(self._matrix_rows_raw):
            for c, btn in enumerate(row):
                if btn is sender:
                    return (c, r)
        return None

    def _current_clip_slot(self):
        song = self._song
        try:
            # Use stored track/scene if in sequencer mode, otherwise use currently selected
            if self._mode and self._sequencer_track is not None and self._sequencer_scene_index is not None:
                track = self._sequencer_track
                scene_index = self._sequencer_scene_index
            else:
                track = song.view.selected_track
                scene = song.view.selected_scene
                scenes = list(song.scenes)
                scene_index = scenes.index(scene)
            
            # Log debug info
            track_name = track.name if hasattr(track, 'name') else 'Unknown'
            self._log("_current_clip_slot: Track='%s' Scene=%d%s" % (track_name, scene_index, " (locked)" if self._mode else ""))
            
            # Check if the track has enough clip slots
            if scene_index >= len(track.clip_slots):
                self._log("Scene index %d >= clip slots count %d - creating missing slots" % (scene_index, len(track.clip_slots)))
                # Try to access the slot anyway - Ableton might auto-create it
                try:
                    slot = track.clip_slots[scene_index]
                    return slot
                except Exception:
                    # If that fails, try scene 0 as fallback
                    if len(track.clip_slots) > 0:
                        self._log("Using scene 0 as fallback")
                        return track.clip_slots[0]
                    else:
                        self._log("No clip slots available on this track")
                        return None
            else:
                slot = track.clip_slots[scene_index]
                return slot
        except Exception as e:
            self._log("_current_clip_slot error: %s" % str(e))
            # Try to fallback to scene 0 on the selected track
            try:
                track = song.view.selected_track
                if len(track.clip_slots) > 0:
                    self._log("Fallback: using scene 0 on selected track")
                    return track.clip_slots[0]
            except Exception:
                pass
            return None

    def _ensure_clip(self):
        slot = self._current_clip_slot()
        if slot is None:
            try:
                self._log("ERROR: _ensure_clip - no clip slot found")
            except Exception:
                pass
            return None
        if not slot.has_clip:
            bars = self._loop_bars_options[self._loop_bars_index]
            length = bars * 4.0
            try:
                self._log("Creating new clip with length %.1f beats" % length)
                slot.create_clip(length)
            except Exception as e:
                try:
                    if self._enable_logging:
                        self._log("ERROR: Failed to create clip: " + str(e))
                except Exception:
                    pass
                return None
        try:
            clip = slot.clip
            # Log clip details for debugging
            try:
                track_name = self._song.view.selected_track.name if hasattr(self._song.view.selected_track, 'name') else 'Unknown'
                scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
                clip_name = clip.name if hasattr(clip, 'name') else 'Unnamed'
                self._log("Accessing clip: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
            except Exception:
                pass
            # Verify it's a MIDI clip
            if clip and hasattr(clip, 'is_midi_clip') and clip.is_midi_clip:
                return clip
            elif clip and hasattr(clip, 'get_notes'):
                # Fallback: if it has get_notes, assume MIDI
                return clip
            else:
                try:
                    if self._enable_logging:
                        self._log("ERROR: Clip is not a MIDI clip or doesn't have get_notes")
                except Exception:
                    pass
        except Exception as e:
            try:
                self._log("ERROR: Exception accessing clip: " + str(e))
            except Exception:
                pass
        return None

    def _apply_loop_length(self):
        clip = self._ensure_clip()
        if clip is None:
            return
        new_bars = self._loop_bars_options[self._loop_bars_index]
        new_end = new_bars * 4.0
        try:
            clip.loop_start = 0.0
            clip.loop_end = new_end
            clip.end_marker = new_end
            # Ensure the clip detail is visible and show the new loop in the clip view
            try:
                self._ensure_clip_detail_visible(clip)
                if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                    clip.view.show_loop()
            except Exception:
                pass
        except Exception:
            pass
        try:
            if hasattr(clip, 'remove_notes_extended'):
                # remove any notes starting after the new loop end across full pitch range
                clip.remove_notes_extended(0, 128, new_end, 9999.0)
            else:
                # Old API: remove_notes(from_time, from_pitch, time_span, pitch_span)
                clip.remove_notes(new_end, 0, 9999.0, 128)
        except Exception:
            pass
        # keep playhead within loop
        try:
            if self._song.is_playing and self._song.current_song_time >= new_end:
                self._song.current_song_time = 0.0
        except Exception:
            pass

    # LED helpers and refresh
    def _set_pad_led(self, col, row, on):
        try:
            btn = self._matrix_rows_raw[row][col]
            if on:
                btn.turn_on()
            else:
                btn.turn_off()
        except Exception:
            pass

    # Tempo change listener for dynamic tick rate adjustment
    def _on_tempo_changed(self):
        try:
            self._current_tempo = float(self._song.tempo)
            # Log tempo changes for debugging
            try:
                self._log("Tempo changed to: %.1f BPM" % self._current_tempo)
            except Exception:
                pass
        except Exception:
            pass

    def _calculate_tick_interval(self):
        """Calculate optimal tick interval based on tempo and note length.
        Returns number of schedule_message ticks (~30ms each) for smooth playhead tracking.
        Dynamically adapts to tempo changes during performance."""
        try:
            # Get current tempo (BPM) from live song tempo (updates automatically)
            tempo = max(20.0, min(999.0, float(self._current_tempo)))  # Clamp to reasonable range
            note_len = float(self._note_lengths[self._note_length_index])
            
            # Calculate time per note in seconds: (60 seconds/minute) / (tempo beats/minute) * note_length_beats
            seconds_per_note = (60.0 / tempo) * note_len
            
            # BALANCED PERFORMANCE: Accurate 16th notes, efficient for longer notes
            # Since we only update LEDs when column actually changes, more checks = more accuracy
            # 16th notes: 2 updates per note for accurate tracking
            # 8th notes: 2 updates per note
            # Quarter+: 2 updates per note
            if note_len <= 0.25:  # 16th notes or faster
                target_updates_per_note = 2.0  # Increased for accuracy
            else:  # All other note lengths
                target_updates_per_note = 2.0
            
            update_interval_seconds = seconds_per_note / target_updates_per_note
            
            # Convert to schedule_message ticks (~30ms per tick)
            # Minimum 3 ticks (90ms) for 16th accuracy, maximum 10 ticks (300ms) for longer notes
            tick_interval = max(3, min(10, int(round(update_interval_seconds / 0.030))))
            
            return tick_interval
        except Exception:
            return 5  # Fallback to reasonable default (150ms)

    def _trigger_note_length_animation(self):
        """Start rainbow animation to visualize note length. Shows full grid for max 4 beats."""
        try:
            self._animation_active = True
            self._animation_counter = 0
            # Record start time in beats for duration tracking
            try:
                self._animation_start_time = float(self._song.current_song_time)
            except Exception:
                self._animation_start_time = 0.0
            
            note_len = self._note_lengths[self._note_length_index]
            self._log("Starting rainbow animation: note length=%.2f beats, max duration=%.1f beats" % (note_len, self._animation_max_duration_beats))
        except Exception as e:
            try:
                self._log("Animation trigger error: " + str(e))
            except Exception:
                pass
    
    def _animate_note_length(self):
        """Show rainbow animation across full grid. Lasts max 4 beats."""
        if not self._animation_active:
            return
            
        try:
            # Check if animation duration exceeded (4 beats max)
            try:
                current_time = float(self._song.current_song_time)
                elapsed_beats = current_time - self._animation_start_time
                if elapsed_beats >= self._animation_max_duration_beats:
                    self._animation_active = False
                    self._animation_counter = 0
                    try:
                        self._log("Rainbow animation ended (%.1f beats elapsed)" % elapsed_beats)
                    except Exception:
                        pass
                    # Restore normal grid display
                    try:
                        self._refresh_grid()
                    except Exception:
                        pass
                    return
            except Exception:
                pass
            
            # Cycle through rainbow colors
            color_idx = self._animation_counter % len(self._rainbow_colors)
            
            # Light up ENTIRE grid (full 8x5) with rainbow wave
            for c in range(self._steps_per_page):
                for r in range(len(self._matrix_rows_raw)):
                    try:
                        # Use rainbow colors with offset per column for wave effect
                        wave_color_idx = (color_idx + c) % len(self._rainbow_colors)
                        self._set_pad_led_color(c, r, self._rainbow_colors[wave_color_idx])
                    except Exception:
                        pass
            
            # Increment animation counter
            self._animation_counter += 1
            
        except Exception as e:
            try:
                self._log("Error in _enter: " + str(e))
            except Exception:
                pass
        
        # CRITICAL: Refresh grid and ensure playhead tracking continues
        try:
            self._refresh_grid()
            self._schedule_tick()
            self._log("Grid refreshed and playhead tracking started")
        except Exception as e:
            try:
                self._log("Error refreshing grid in _enter: " + str(e))
            except Exception:
                pass
            self._animation_active = False


    # Blinking playhead
    def _schedule_tick(self):
        try:
            tick_interval = self._calculate_tick_interval()
            self._cs.schedule_message(tick_interval, self._tick)
        except Exception:
            pass

    def _tick(self):
        # Stop ticking if sequencer mode is not active
        if not self._mode:
            return
        
        # Prevent multiple simultaneous tick executions (performance optimization)
        if self._tick_in_progress:
            return
        
        try:
            self._tick_in_progress = True
            
            # Run animation if active (takes priority over playhead blink)
            if self._animation_active:
                try:
                    self._animate_note_length()
                except Exception:
                    pass
            else:
                # Always show playhead (but optimized to only update on column change)
                self._update_blink()
            
            # Update display for scene preview (only when needed)
            if self._scene_preview_active:
                try:
                    self._update_display()
                except Exception:
                    pass
        finally:
            self._tick_in_progress = False
            self._schedule_tick()

    def _update_blink(self):
        try:
            bars = self._loop_bars_options[self._loop_bars_index]
            loop_len = bars * 4.0
            note_len = self._note_lengths[self._note_length_index]
            
            # PERFORMANCE OPTIMIZED: Use cached clip with playing_position for accurate tracking
            pos = 0.0
            clip = self._get_cached_clip()
            if clip and hasattr(clip, 'playing_position'):
                try:
                    # Live 12 API: playing_position gives exact position within the clip loop
                    pos = float(clip.playing_position)
                except Exception:
                    # Fallback to song time if property access fails
                    pos = self._song.current_song_time % max(loop_len, 0.0001)
            else:
                # No clip or no playing_position - use song time
                pos = self._song.current_song_time % max(loop_len, 0.0001)
            
            step_idx = int(pos / max(note_len, 0.0001))
            col = step_idx % self._steps_per_page
            
            # SCALE CHANGE DETECTION: Check for scale changes at loop boundaries (improv sets)
            try:
                # Detect loop restart (step index wrapped to 0 or near 0)
                if not hasattr(self, '_last_step_idx'):
                    self._last_step_idx = 0
                
                # Check if we wrapped around (completed a loop)
                if step_idx < self._last_step_idx or (step_idx == 0 and self._last_step_idx > 2):
                    # Loop completed, check for scale changes
                    self._detect_scale(check_for_changes=True)
                    # After scale check, refresh grid if notes became chromatic
                    if len(self._chromatic_blink_notes) > 0:
                        self._chromatic_blink_count = 0  # Reset blink counter
                        self._refresh_grid()
                
                self._last_step_idx = step_idx
            except Exception:
                pass
            
            # Update loop position indicator on clip stop buttons (for all note lengths)
            try:
                # Calculate which "page" of the loop we're currently on
                current_page = step_idx // self._steps_per_page
                
                # Calculate loop length in pages (round up for partial pages)
                total_steps = int(loop_len / note_len)
                loop_length_pages = max(1, (total_steps + self._steps_per_page - 1) // self._steps_per_page)
                
                # Update clip stop buttons
                for i, btn in enumerate(self._clip_stop_buttons_raw):
                    try:
                        if i == current_page:
                            # Blink the current playhead position button
                            # Pink if on visible grid, Red if off visible grid
                            if i == self._time_page:
                                # On visible grid - use PINK
                                color = self._LED_PINK if self._clip_stop_blink_state else 0
                            else:
                                # Off visible grid - use RED
                                color = self._LED_RED if self._clip_stop_blink_state else 0
                            btn.send_value(color, True)
                        elif i < loop_length_pages:
                            # Keep loop length button lit (dim yellow/orange)
                            btn.send_value(self._LED_ORANGE, True)
                        else:
                            # Turn off buttons beyond loop length
                            btn.send_value(0, True)
                    except Exception:
                        pass
                
                # Toggle blink state each tick for smooth blinking
                self._clip_stop_blink_state = not self._clip_stop_blink_state
                self._last_loop_position_page = current_page
                
                # Clear chromatic blink notes after ~10 blinks (visual indicator fades)
                if len(self._chromatic_blink_notes) > 0:
                    if not hasattr(self, '_chromatic_blink_count'):
                        self._chromatic_blink_count = 0
                    self._chromatic_blink_count += 1
                    if self._chromatic_blink_count > 20:  # ~20 ticks = 10 blinks
                        self._chromatic_blink_notes.clear()
                        self._chromatic_blink_count = 0
                        self._refresh_grid()  # Restore normal coloring
            except Exception:
                pass
            
            # Playhead logging disabled for performance (only enable when debugging)
            # Log playhead position for debugging (reduced frequency to avoid spam)
            # try:
            #     if step_idx % 8 == 0:  # Log every 8 steps for verification
            #         tick_interval = self._calculate_tick_interval()
            #         # Also log comparison with song time to verify accuracy
            #         try:
            #             clip = self._ensure_clip()
            #             song_time = float(self._song.current_song_time)
            #             method = "unknown"
            #             if clip and hasattr(clip, 'playing_position'):
            #                 method = "clip.playing_position"
            #             elif clip and hasattr(clip, 'loop_start'):
            #                 method = "song_time - loop_start"
            #             else:
            #                 method = "song_time (fallback)"
            #             self._log("Playhead [%s]: pos=%.3f song_time=%.3f step=%d col=%d page=%d note_len=%.2f tempo=%.1f" % (method, pos, song_time, step_idx, col, step_idx // self._steps_per_page, note_len, self._current_tempo))
            #         except Exception:
            #             self._log("Playhead: pos=%.3f step=%d col=%d page=%d note_len=%.2f tempo=%.1f tick=%d" % (pos, step_idx, col, step_idx // self._steps_per_page, note_len, self._current_tempo, tick_interval))
            # except Exception:
            #     pass
        except Exception as e:
            col = None
            try:
                self._log("Blink calc error: " + str(e))
            except Exception:
                pass
        
        # PERFORMANCE OPTIMIZED: Only update LEDs when column actually changes
        if col != self._last_blink_col:
            # Restore previous column to normal state
            if self._last_blink_col is not None:
                for r in range(len(self._matrix_rows_raw)):
                    self._redraw_cell(self._last_blink_col, r)
            
            # Show RED playhead bar on new column (solid, no blinking for performance)
            if col is not None:
                for r in range(len(self._matrix_rows_raw)):
                    try:
                        # ABLETON LAYOUT: Use inverted row indexing for playhead
                        row_offset = (self._drum_row_base + self._rows_visible - 1) - r
                        if row_offset >= len(self._row_note_offsets) or row_offset < 0:
                            continue
                        
                        # Show WHITE playhead bar on ALL rows (matches Ableton's white bar)
                        self._set_pad_led_color(col, r, self._LED_WHITE)
                    except Exception:
                        pass
        # If column hasn't changed, do nothing (saves CPU and LED traffic)
        
        self._last_blink_col = col
        
        # Handle scene preview: blink scene launch buttons in function color
        if self._scene_preview_active:
            try:
                # Light scene buttons in preview color (no OFF phase for faster feedback)
                try:
                    for btn in self._scene_launch_buttons_raw:
                        btn.send_value(self._scene_preview_color, True)
                except Exception as e:
                    try:
                        self._log("Error lighting scene buttons: " + str(e))
                    except Exception:
                        pass
                
                # Increment blink count every tick
                self._scene_preview_count += 1
                
                # Check if preview is complete
                if self._scene_preview_count >= self._scene_preview_target:
                    try:
                        self._log("Scene preview complete - %d blinks done" % self._scene_preview_count)
                    except Exception:
                        pass
                    
                    # Turn off all scene buttons
                    try:
                        for btn in self._scene_launch_buttons_raw:
                            btn.send_value(0, True)
                    except Exception:
                        pass
                    
                    # Turn off Stop All LED
                    try:
                        if self._stop_all_button:
                            self._stop_all_button.send_value(0, True)
                            self._log("Stop All LED turned OFF")
                    except Exception:
                        pass
                    
                    # Now apply the function rotation
                    self._scene_preview_active = False
                    if self._pending_function_rotation:
                        try:
                            current_idx = self._function_colors.index(self._current_function_color)
                            next_idx = (current_idx + 1) % len(self._function_colors)
                            self._current_function_color = self._function_colors[next_idx]
                            self._log("Function rotation applied: new color = %d" % self._current_function_color)
                        except Exception:
                            self._current_function_color = self._function_colors[0]
                        self._pending_function_rotation = False
                        # Log the new function
                        try:
                            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                                         self._LED_GREEN: "FILL WHOLE"}
                            func_name = func_names.get(self._current_function_color, "UNKNOWN")
                            self._log("Function now selected: %s" % func_name)
                        except Exception:
                            pass
                        # Update scene LEDs to show current function assignments
                        try:
                            self._render_scene_function_leds()
                        except Exception:
                            pass
            except Exception as e:
                try:
                    if self._enable_logging:
                        self._log("Scene preview error: " + str(e))
                except Exception:
                    pass
                self._scene_preview_active = False
                self._pending_function_rotation = False
                # Clean up: turn off scene buttons and Stop All
                try:
                    for btn in self._scene_launch_buttons_raw:
                        btn.send_value(0, True)
                    if self._stop_all_button:
                        self._stop_all_button.send_value(0, True)
                except Exception:
                    pass

        # Handle function button blinks (for buttons that can't change color)
        if self._function_button_blink_count < self._function_button_blink_target:
            # Toggle blink state every few ticks for visible flash
            self._function_button_blink_phase = (self._function_button_blink_phase + 1) % 6
            if self._function_button_blink_phase == 0:
                # Turn on Stop All button (function indicator)
                try:
                    if self._stop_all_button:
                        self._stop_all_button.send_value(127, True)  # Bright orange
                except Exception:
                    pass
                self._function_button_blink_count += 1
            elif self._function_button_blink_phase == 3:
                # Turn off Stop All button
                try:
                    if self._stop_all_button:
                        self._stop_all_button.send_value(0, True)
                except Exception:
                    pass
        elif self._function_button_blink_target > 0 and self._function_button_blink_count >= self._function_button_blink_target:
            # Blink complete - ensure Stop All is OFF (no steady)
            try:
                if self._stop_all_button:
                    self._stop_all_button.send_value(0, True)
            except Exception:
                pass
            self._function_button_blink_target = 0
            self._function_button_blink_count = 0
            self._function_button_blink_phase = 0

        # Handle master button blinks for execution feedback
        if self._master_button_blink_count < self._master_button_blink_target:
            # Toggle blink state every few ticks for visible flash
            self._master_button_blink_phase = (self._master_button_blink_phase + 1) % 6
            if self._master_button_blink_phase == 0:
                # Turn on Master button
                try:
                    if self._master_button:
                        self._master_button.send_value(127, True)  # Bright orange
                except Exception:
                    pass
                self._master_button_blink_count += 1
            elif self._master_button_blink_phase == 3:
                # Turn off Master button
                try:
                    if self._master_button:
                        self._master_button.send_value(0, True)
                except Exception:
                    pass
        elif self._master_button_blink_target > 0 and self._master_button_blink_count >= self._master_button_blink_target:
            # Blink complete - ensure Master is OFF
            try:
                if self._master_button:
                    self._master_button.send_value(0, True)
            except Exception:
                pass
            self._master_button_blink_target = 0
            self._master_button_blink_count = 0
            self._master_button_blink_phase = 0

    def _has_note_overlap_at(self, clip, pitch, start, step_duration):
        """Detect if a note STARTS at this step (anchor) within a dynamic epsilon window.
        EPS adapts to grid resolution to avoid false negatives and never spans to previous step."""
        try:
            sd = float(step_duration)
            eps = max(0.001, min(0.02, 0.2 * sd))
            # Use absolute clip time by adding loop_start offset
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
            except Exception:
                loop_start = 0.0
            from_time = max(0.0, float(loop_start) + float(start) - eps)
            time_span = max(2.0 * eps, 0.004)
            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(int(pitch), 1, from_time, time_span)
            else:
                existing = clip.get_notes(from_time, int(pitch), time_span, 1)
            return bool(existing)
        except Exception:
            return False

    def _redraw_cell(self, col, row):
        # ABLETON LAYOUT: Invert row indexing
        row_offset = (self._drum_row_base + self._rows_visible - 1) - row
        if row_offset >= len(self._row_note_offsets) or row_offset < 0:
            return
        pitch = self._row_note_offsets[row_offset]
        step = col + self._time_page * self._steps_per_page
        note_len = self._note_lengths[self._note_length_index]
        start = step * note_len
        clip = self._get_cached_clip()
        # Use actual clip loop length if available for bounds check
        try:
            clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
            if clip_loop_len <= 0.0:
                clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
        except Exception:
            clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
        if clip is None or start >= clip_loop_len:
            # Don't clear LEDs when clip access fails - keep existing state
            return
        has_note = False
        try:
            has_note = self._has_note_overlap_at(clip, pitch, float(start), float(note_len))
        except Exception:
            has_note = False
        
        # SCALE-AWARE COLOR CODING (melodic instruments only, same as _refresh_grid)
        if self._is_drum_rack:
            # DRUMS: Simple green/blue coloring, no scale awareness
            if row_offset == self._selected_drum:
                color = self._LED_GREEN if has_note else self._LED_BLUE
            else:
                color = self._LED_GREEN if has_note else 0
        else:
            # MELODIC: Scale-aware coloring with blinking for newly chromatic notes
            in_scale = pitch in self._scale_notes
            is_root = (pitch % 12) == (self._root_note % 12)
            is_newly_chromatic = has_note and pitch in self._chromatic_blink_notes
            
            if row_offset == self._selected_drum:
                # Selected row: always blue when empty, green when has note
                color = self._LED_GREEN if has_note else self._LED_BLUE
            else:
                # Other rows: Scale-aware coloring
                if has_note:
                    if is_newly_chromatic:
                        # Blink newly chromatic notes (alternate ORANGE/OFF)
                        color = self._LED_ORANGE if self._clip_stop_blink_state else 0
                    elif in_scale:
                        # Normal in-scale note
                        color = self._LED_GREEN
                    else:
                        # Chromatic note (was already chromatic)
                        color = self._LED_ORANGE
                else:
                    # Empty: BLUE (dim) if in scale, OFF if chromatic, CYAN if root
                    if is_root:
                        color = self._LED_CYAN  # Root note indicator
                    elif in_scale:
                        color = self._LED_BLUE  # In-scale note available
                    else:
                        color = 0  # Chromatic note (off)
        self._set_pad_led_color(col, row, color)

    def _clear_blink(self):
        if self._last_blink_col is not None:
            for r in range(len(self._matrix_rows_raw)):
                self._redraw_cell(self._last_blink_col, r)
        self._last_blink_col = None

    def _update_display(self):
        # Update LEDs and display based on current state
        try:
            # Handle scene preview if active
            if self._scene_preview_active:
                try:
                    self._scene_preview_count += 1
                    
                    # Show solid color during preview (no blinking)
                    color = self._scene_preview_color
                    
                    # Update all scene launch buttons with the color
                    for i in range(len(self._scene_launch_buttons_raw)):
                        try:
                            if hasattr(self._scene_launch_buttons_raw[i], 'send_value'):
                                self._scene_launch_buttons_raw[i].send_value(color, True)
                            else:
                                self._log("Scene button %d has no send_value method" % i)
                        except Exception as e:
                            self._log("Error updating scene button %d: %s" % (i, str(e)))
                    
                    # Check if preview is complete
                    if self._scene_preview_count >= self._scene_preview_target:
                        self._scene_preview_active = False
                        self._log("Scene preview completing after %d ticks" % self._scene_preview_count)
                        # Apply function rotation if pending
                        if self._pending_function_rotation:
                            old_color = self._current_function_color
                            self._current_function_color = self._scene_preview_color
                            self._pending_function_rotation = False
                            self._log("Function rotation applied: %d -> %d" % (old_color, self._current_function_color))
                        # Update scene LEDs to show current assignments
                        try:
                            self._render_scene_function_leds()
                            self._log("Scene LEDs updated to show current drum function assignments")
                        except Exception as e:
                            self._log("Error updating scene LEDs: %s" % str(e))
                        self._log("Scene preview complete - %d ticks done" % self._scene_preview_count)
                except Exception as e:
                    try:
                        self._log("Scene preview error: " + str(e))
                    except Exception:
                        pass
        except Exception as e:
            try:
                self._log("Display update error: " + str(e))
            except Exception:
                pass

    def _on_scene_launch_button(self, button_index, value):
        # Scene launch buttons cycle the function assignment per drum (0 -> RED -> YELLOW -> ... -> 0)
        if not value or not self._mode:
            return
        try:
            # ABLETON LAYOUT: Scene button to drum index mapping (inverted)
            # Button 0 (top) = highest visible note, Button 4 (bottom) = lowest
            drum_index = (self._drum_row_base + self._rows_visible - 1) - button_index
            if drum_index >= len(self._row_note_offsets):
                return
            
            # Determine current assignment value (int), handling legacy set format
            current_assigned = 0
            if drum_index in self._drum_functions:
                try:
                    assigned_obj = self._drum_functions[drum_index]
                    if isinstance(assigned_obj, set):
                        current_assigned = int(min(assigned_obj)) if len(assigned_obj) > 0 else 0
                    else:
                        current_assigned = int(assigned_obj)
                except Exception:
                    current_assigned = 0
            # Cycle to next function in order (including 0 for NONE)
            try:
                cycle = list(self._function_colors)
                idx = cycle.index(current_assigned) if current_assigned in cycle else 0
            except Exception:
                cycle = list(self._function_colors)
                idx = 0
            next_idx = (idx + 1) % len(cycle)
            new_color = int(cycle[next_idx])

            # Store single int assignment per drum (0 means clear assignment)
            if new_color == 0:
                try:
                    del self._drum_functions[drum_index]
                except Exception:
                    pass
            else:
                self._drum_functions[drum_index] = new_color

            # Maintain ordered COPY/PASTE queues
            try:
                self._ensure_copy_paste_queues()
                if new_color == self._LED_YELLOW:
                    if drum_index not in self._copy_queue:
                        self._copy_queue.append(drum_index)
                elif current_assigned == self._LED_YELLOW and drum_index in self._copy_queue:
                    self._copy_queue.remove(drum_index)
                if new_color == self._LED_ORANGE:
                    if drum_index not in self._paste_queue:
                        self._paste_queue.append(drum_index)
                elif current_assigned == self._LED_ORANGE and drum_index in self._paste_queue:
                    self._paste_queue.remove(drum_index)
            except Exception:
                pass

            # Update LED immediately to new color
            try:
                btn = self._scene_launch_buttons_raw[button_index]
                btn.send_value(new_color, True)
            except Exception:
                pass

            # Log human-friendly function name
            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                         self._LED_GREEN: "FILL WHOLE"}
            func_name = func_names.get(new_color, "UNKNOWN")
            self._log("Drum %d set function: %s" % (drum_index, func_name))
            
            # Update scene function LEDs to reflect current state
            try:
                self._render_scene_function_leds()
            except Exception:
                pass
        except Exception as e:
            try:
                self._log("Scene launch button error: " + str(e))
            except Exception:
                pass

    def _on_stop_all_button(self, value):
        # Stop all clips button cycles through function colors
        if not value or not self._mode:
            try:
                return
            except Exception:
                pass
        
        # Handle function cycling with immediate scene display
        try:
            # If preview is already active, apply the current rotation immediately and move to next
            if self._scene_preview_active:
                self._scene_preview_active = False
                if self._pending_function_rotation:
                    self._current_function_color = self._scene_preview_color
                    self._pending_function_rotation = False
                    self._log("Function rotation applied immediately: new color = %d" % self._current_function_color)
                    func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                                 self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                                 self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                                 self._LED_GREEN: "FILL WHOLE"}
                    self._log("Function now selected: %s" % func_names.get(self._current_function_color, "UNKNOWN"))
            
            # Determine next function color
            try:
                current_idx = self._function_colors.index(self._current_function_color)
            except ValueError:
                current_idx = 0
            next_idx = (current_idx + 1) % len(self._function_colors)
            next_color = self._function_colors[next_idx]
            
            # Log the function change
            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                         self._LED_GREEN: "FILL WHOLE"}
            current_func = func_names.get(self._current_function_color, "UNKNOWN")
            next_func = func_names.get(next_color, "UNKNOWN")
            self._log("Cycling function: %s -> %s" % (current_func, next_func))
            
            # Do NOT turn Stop All LED on or blink it - as per user preference
            # Commented out: self._stop_all_button.send_value(self._LED_ORANGE, True)
            # Note: We do not use blinks on Stop All button to show function as per user request
            
            # Immediately update scene buttons to show the new function color
            try:
                for i in range(len(self._scene_launch_buttons_raw)):
                    if hasattr(self._scene_launch_buttons_raw[i], 'send_value'):
                        self._scene_launch_buttons_raw[i].send_value(next_color, True)
                        self._log("Scene button %d updated to color %d" % (i, next_color))
                    else:
                        self._log("Scene button %d has no send_value method" % i)
            except Exception as e:
                self._log("Error updating scene buttons: %s" % str(e))
            
            # Set up scene preview: show scene buttons in the new function color briefly
            self._scene_preview_active = True
            self._scene_preview_color = next_color
            self._scene_preview_count = 0
            self._scene_preview_target = 5  # Short duration, ~0.5-1 second
            self._scene_preview_phase = 0
            self._pending_function_rotation = True
            
            self._log("Scene display updated: showing color %s for %d ticks" % (next_func, self._scene_preview_target))
            self._log("Current function before preview: %d, Next function: %d" % (self._current_function_color, next_color))
        except Exception as e:
            try:
                self._log("Stop all button error: " + str(e))
            except Exception:
                pass
    
    def _on_master_button(self, value):
        # Master button executes currently selected function on ALL drums with that function assigned
        if not value or not self._mode:
            return
        try:
            # Log current function state for debugging
            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                         self._LED_GREEN: "FILL WHOLE"}
            current_func_name = func_names.get(self._current_function_color, "UNKNOWN")
            self._log("Master button pressed - current function: %d (%s)" % (self._current_function_color, current_func_name))
            
            # Find all drums with the currently selected function color
            drums_to_execute = []
            for drum_idx, assigned in self._drum_functions.items():
                try:
                    if isinstance(assigned, set):
                        if int(self._current_function_color) in assigned:
                            drums_to_execute.append(drum_idx)
                    elif isinstance(assigned, int):
                        if assigned == int(self._current_function_color):
                            drums_to_execute.append(drum_idx)
                except Exception:
                    continue
            
            if not drums_to_execute:
                # No drums assigned to this function - blink Master button 5 times as error
                try:
                    self._master_blink_active = True
                    self._master_blink_count = 0
                    self._master_blink_target = 5  # 5 blinks for error
                    self._master_blink_phase = 0
                    self._log("No drums assigned to function %d - error blink started" % self._current_function_color)
                except Exception:
                    pass
                return
            
            # Execute the function based on color
            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                         self._LED_GREEN: "FILL WHOLE"}
            func_name = func_names.get(self._current_function_color, "UNKNOWN")
            self._log("Executing %s on %d drums: %s" % (func_name, len(drums_to_execute), str(drums_to_execute)))
            
            if self._current_function_color == self._LED_RED:  # CLEAR
                for drum_idx in drums_to_execute:
                    try:
                        self._clear_drum_notes(drum_idx)
                    except Exception as e:
                        self._log("Error clearing drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color == self._LED_YELLOW:  # COPY
                for drum_idx in drums_to_execute:
                    try:
                        self._copy_drum_notes(drum_idx)
                    except Exception as e:
                        self._log("Error copying drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color == self._LED_ORANGE:  # PASTE
                for drum_idx in drums_to_execute:
                    try:
                        self._paste_drum_notes(drum_idx)
                    except Exception as e:
                        self._log("Error pasting drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color in [self._LED_PURPLE, self._LED_DARK_PURPLE, self._LED_LIME, self._LED_GREEN]:  # FILL
                duration = {self._LED_PURPLE: 1.0, self._LED_DARK_PURPLE: 0.5, self._LED_LIME: 0.25, self._LED_GREEN: 4.0}[self._current_function_color]
                for drum_idx in drums_to_execute:
                    try:
                        self._fill_drum_notes(drum_idx, duration)
                    except Exception as e:
                        self._log("Error filling drum %d: %s" % (drum_idx, str(e)))
            
            # Clear the executed function from assignments
            for drum_idx in drums_to_execute:
                try:
                    if drum_idx in self._drum_functions:
                        if isinstance(self._drum_functions[drum_idx], set):
                            self._drum_functions[drum_idx].discard(int(self._current_function_color))
                            if not self._drum_functions[drum_idx]:
                                del self._drum_functions[drum_idx]
                        else:
                            del self._drum_functions[drum_idx]
                except Exception:
                    pass
            
            # Update scene LEDs to reflect changes
            try:
                self._render_scene_function_leds()
            except Exception:
                pass
            
            # Restore clip detail view to ensure clip stays visible and ready for editing
            try:
                clip = self._ensure_clip()
                if clip:
                    self._ensure_clip_detail_visible(clip)
                    if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                        clip.view.show_loop()
                    self._log("Clip detail view restored after function execution")
            except Exception:
                pass
            
            # Blink Master button 3 times for success feedback
            try:
                self._master_blink_active = True
                self._master_blink_count = 0
                self._master_blink_target = 3  # 3 blinks for success
                self._master_blink_phase = 0
                self._log("Function %s executed on %d drums - success blink started" % (func_name, len(drums_to_execute)))
            except Exception:
                pass
            
            # Reset function to NONE after execution
            self._current_function_color = 0
            self._log("Function reset to NONE after execution")
        except Exception as e:
            try:
                self._log("Master button error: " + str(e))
            except Exception:
                pass
    
    def _clear_drum_notes(self, drum_index):
        # Clear all notes for the specified drum by directly removing all notes
        clip = self._get_cached_clip()
        if clip is None:
            return
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
            except Exception:
                loop_start = 0.0
            note_len = self._note_lengths[self._note_length_index]
            
            # Directly remove all notes for this drum within the loop
            self._log("Clearing drum %d (pitch %d) directly" % (drum_index, pitch))
            if hasattr(clip, 'remove_notes_extended'):
                clip.remove_notes_extended(pitch, 1, float(loop_start), float(loop_len))
            else:
                clip.remove_notes(float(loop_start), pitch, float(loop_len), 1)
            
            # Refresh entire grid to ensure consistency
            try:
                self._refresh_grid()
                self._log("Grid refreshed after clearing drum %d" % drum_index)
            except Exception as e:
                self._log("Error refreshing grid after clear: " + str(e))
            
            self._log("Cleared all notes for drum %d (pitch %d)" % (drum_index, pitch))
        except Exception as e:
            try:
                self._log("Clear drum notes error: " + str(e))
            except Exception:
                pass

    def _copy_drum_notes(self, drum_index):
        # Copy all notes for the specified drum to buffer
        clip = self._get_cached_clip()
        if clip is None:
            return
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
                clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                if clip_loop_len <= 0.0:
                    clip_loop_len = float(loop_len)
            except Exception:
                loop_start = 0.0
                clip_loop_len = float(loop_len)
            
            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(int(pitch), 1, float(loop_start), float(clip_loop_len))
            else:
                notes = clip.get_notes(float(loop_start), int(pitch), float(clip_loop_len), 1)
            
            # Store notes as simple data (time, duration, velocity) for easy pasting
            self._copied_notes = []
            for note in notes:
                try:
                    if hasattr(note, 'start_time'):
                        # Store times relative to loop_start
                        self._copied_notes.append({
                            'start': float(max(0.0, float(note.start_time) - float(loop_start))),
                            'duration': float(note.duration),
                            'velocity': int(getattr(note, 'velocity', 100))
                        })
                    else:
                        # Old API tuple format (time, pitch, duration, velocity, mute)
                        # Old API tuple: (pitch, start_time, duration, velocity, mute)
                        rel_start = float(max(0.0, float(note[1]) - float(loop_start)))
                        self._copied_notes.append({
                            'start': rel_start,
                            'duration': float(note[2]),
                            'velocity': int(note[3]) if len(note) > 3 else 100
                        })
                except Exception:
                    continue
            
            self._log("Copied %d notes from drum %d (pitch %d) - READ ONLY, source unchanged" % (len(self._copied_notes), drum_index, pitch))
        except Exception as e:
            try:
                self._log("Copy drum notes error: " + str(e))
            except Exception:
                pass

    def _paste_drum_notes(self, drum_index):
        # Paste copied notes to the specified drum
        if not hasattr(self, '_copied_notes') or not self._copied_notes:
            self._log("PASTE FAILED: No notes to paste - copy some notes first")
            return
        
        clip = self._get_cached_clip()
        if clip is None:
            self._log("PASTE FAILED: No clip available - make sure you're on a track with a clip")
            self._log("PASTE TIP: Stay on the same drum track where you copied the notes")
            return
        
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
                clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                if clip_loop_len <= 0.0:
                    clip_loop_len = float(loop_len)
            except Exception:
                loop_start = 0.0
                clip_loop_len = float(loop_len)
            
            # Prepare notes for pasting using Live 12 API
            notes_to_add = []
            for note_data in self._copied_notes:
                try:
                    # Calculate absolute time (relative to clip start)
                    abs_start = float(loop_start) + float(note_data['start'])
                    
                    # Only paste notes that fit within the loop
                    if abs_start < (loop_start + clip_loop_len):
                        # Create MidiNoteSpecification with all params in constructor
                        note_spec = Live.Clip.MidiNoteSpecification(
                            pitch=int(pitch),
                            start_time=float(abs_start),
                            duration=float(note_data['duration']),
                            velocity=float(note_data['velocity']),
                            mute=False
                        )
                        notes_to_add.append(note_spec)
                except Exception as e:
                    try:
                        self._log("Failed to create note spec: " + str(e))
                    except Exception:
                        pass
                    continue
            
            # Add all notes at once using Live 12 API
            if notes_to_add:
                clip.add_new_notes(tuple(notes_to_add))
                
                self._log("Pasted %d notes to drum %d (pitch %d) - other drums unaffected" % (len(notes_to_add), drum_index, pitch))
                
                # Immediately refresh grid to show pasted notes
                try:
                    self._refresh_grid()
                    self._log("Grid refreshed - pasted notes now visible")
                except Exception as e:
                    try:
                        self._log("Grid refresh after paste failed: " + str(e))
                    except Exception:
                        pass
            else:
                self._log("No notes pasted - all notes were outside loop bounds")
                
        except Exception as e:
            try:
                self._log("Paste drum notes error: " + str(e))
            except Exception:
                pass

    def _fill_drum_notes(self, drum_index, note_duration):
        # Fill drum with notes at the specified duration intervals
        clip = self._get_cached_clip()
        if clip is None:
            self._log("FILL FAILED: No clip available - make sure you're on a track with a clip")
            return
        
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
                clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                if clip_loop_len <= 0.0:
                    clip_loop_len = float(loop_len)
            except Exception:
                loop_start = 0.0
                clip_loop_len = float(loop_len)
            
            # Generate fill pattern notes using Live 12 API
            notes_to_add = []
            current_time = loop_start
            velocity = 100  # Default velocity for fill notes
            
            while current_time < (loop_start + clip_loop_len):
                try:
                    # Create MidiNoteSpecification with all params in constructor
                    note_spec = Live.Clip.MidiNoteSpecification(
                        pitch=int(pitch),
                        start_time=float(current_time),
                        duration=float(note_duration),
                        velocity=float(velocity),
                        mute=False
                    )
                    notes_to_add.append(note_spec)
                except Exception as e:
                    try:
                        self._log("Failed to create fill note spec: " + str(e))
                    except Exception:
                        pass
                
                current_time += note_duration
            
            # Add all notes at once using Live 12 API
            if notes_to_add:
                clip.add_new_notes(tuple(notes_to_add))
                
                # Determine fill type for logging
                fill_types = {1.0: "quarter", 0.5: "eighth", 0.25: "sixteenth", 4.0: "whole"}
                fill_type = fill_types.get(note_duration, "%.2f beat" % note_duration)
                
                self._log("Filled drum %d with %d %s notes (pitch %d) - other drums unaffected" % (drum_index, len(notes_to_add), fill_type, pitch))
                
                # Immediately refresh grid to show filled notes
                try:
                    self._refresh_grid()
                    self._log("Grid refreshed - filled notes now visible")
                except Exception as e:
                    try:
                        self._log("Grid refresh after fill failed: " + str(e))
                    except Exception:
                        pass
            else:
                self._log("No fill notes added - loop too short")
                
        except Exception as e:
            try:
                self._log("Fill drum notes error: " + str(e))
            except Exception:
                pass

    def _get_drum_notes(self, drum_index):
        clip = self._get_cached_clip()
        if clip is None:
            return []
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
                clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                if clip_loop_len <= 0.0:
                    clip_loop_len = float(loop_len)
            except Exception:
                loop_start = 0.0
                clip_loop_len = float(loop_len)
            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(int(pitch), 1, float(loop_start), float(clip_loop_len))
            else:
                notes = clip.get_notes(float(loop_start), int(pitch), float(clip_loop_len), 1)
            res = []
            for n in notes or []:
                try:
                    if hasattr(n, 'start_time'):
                        res.append({'start': float(max(0.0, float(n.start_time) - float(loop_start))), 'duration': float(n.duration), 'velocity': int(getattr(n, 'velocity', 100))})
                    else:
                        s = float(max(0.0, float(n[1]) - float(loop_start)))
                        res.append({'start': s, 'duration': float(n[2]), 'velocity': int(n[3]) if len(n) > 3 else 100})
                except Exception:
                    continue
            return res
        except Exception:
            return []

    def _paste_notes_to_drum(self, drum_index, notes_data):
        clip = self._get_cached_clip()
        if clip is None:
            return
        try:
            target_pitch = self._row_note_offsets[drum_index]
            # Safety check: ensure index is within buffer bounds
            if drum_index >= len(self._drum_pressure):
                pressure = 0
            else:
                pressure = self._drum_pressure[drum_index]
            # Determine clip loop length from clip if available
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
                clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
                if clip_loop_len <= 0.0:
                    clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
            except Exception:
                loop_start = 0.0
                clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
            
            # Create new notes at target pitch from copied data
            new_notes = []
            for nd in (notes_data or []):
                try:
                    start = float(nd.get('start', 0.0))
                    duration = float(nd.get('duration', 0.0))
                    vel = int(nd.get('velocity', 100))
                    # Clamp start into loop range to ensure visibility
                    if clip_loop_len > 0.0:
                        start = start % clip_loop_len
                        if start + duration > clip_loop_len:
                            duration = max(0.01, clip_loop_len - start)
                    
                    # Use Live 12 API - add loop_start offset back to absolute clip time
                    note_spec = Live.Clip.MidiNoteSpecification(
                        pitch=int(target_pitch),
                        start_time=float(loop_start) + float(start),
                        duration=float(duration),
                        velocity=int(vel),
                        mute=False,
                        release_velocity=int(pressure)
                    )
                    new_notes.append(note_spec)
                except Exception:
                    continue
            if new_notes:
                if hasattr(clip, 'add_new_notes'):
                    clip.add_new_notes(tuple(new_notes))
                else:
                    # Fallback for old API: merge with existing notes instead of replacing
                    try:
                        # Gather all existing notes across full pitch range and loop window
                        loop_start_abs = float(getattr(clip, 'loop_start', 0.0))
                        existing = clip.get_notes(loop_start_abs, 0, clip_loop_len, 128)
                    except Exception:
                        existing = []
                    # Convert existing from (pitch, start, dur, vel, mute) -> (start, pitch, dur, vel, mute)
                    merged = []
                    for ex in (existing or []):
                        try:
                            merged.append((float(ex[1]), int(ex[0]), float(ex[2]), int(ex[3]) if len(ex) > 3 else 100, bool(ex[4]) if len(ex) > 4 else False))
                        except Exception:
                            continue
                    # Append new tuples
                    for ns in new_notes:
                        try:
                            merged.append((float(ns.start_time), int(ns.pitch), float(ns.duration), int(getattr(ns, 'velocity', 100)), False))
                        except Exception:
                            continue
                    if merged:
                        clip.set_notes(tuple(merged))
                self._log("Pasted %d notes to drum %d (pitch %d) - other drums unaffected" % (len(new_notes), drum_index, target_pitch))
            else:
                self._log("No valid notes to paste")
            
            # Ensure clip detail remains visible
            try:
                self._ensure_clip_detail_visible(clip)
                if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                    clip.view.show_loop()
            except Exception:
                pass
        except Exception as e:
            try:
                self._log("Paste drum notes error: " + str(e))
            except Exception:
                pass

    def _fill_quarter_notes(self, drum_index):
        # Place a quarter note (1 beat) on every beat of the bar
        self._fill_pattern(drum_index, 1.0, "quarter notes")

    def _fill_eighth_notes(self, drum_index):
        # Place an eighth note (0.5 beats) on every eighth note position
        self._fill_pattern(drum_index, 0.5, "eighth notes")

    def _fill_sixteenth_notes(self, drum_index):
        # Place a sixteenth note (0.25 beats) on every sixteenth note position
        self._fill_pattern(drum_index, 0.25, "sixteenth notes")

    def _fill_whole_notes(self, drum_index):
        # Place a whole note (4 beats) on every whole note position
        self._fill_pattern(drum_index, 4.0, "whole notes")

    def _fill_pattern(self, drum_index, note_spacing, pattern_name):
        # Fill the drum with notes at regular intervals
        clip = self._get_cached_clip()
        if clip is None:
            return
        
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
            except Exception:
                loop_start = 0.0
            # Safety check: ensure index is within buffer bounds
            if drum_index >= len(self._drum_velocity) or drum_index >= len(self._drum_pressure):
                velocity = 64
                pressure = 0
            else:
                velocity = self._drum_velocity[drum_index]
                pressure = self._drum_pressure[drum_index]
            
            # Generate notes at regular intervals
            new_notes = []
            pos = 0.0
            while pos < loop_len:
                # Note duration is the spacing (to avoid overlaps)
                duration = min(note_spacing, loop_len - pos)
                
                # Use Live 12 API
                note_spec = Live.Clip.MidiNoteSpecification(
                    pitch=int(pitch),
                    start_time=float(loop_start) + float(pos),
                    duration=float(duration),
                    velocity=int(velocity),
                    mute=False,
                    release_velocity=int(pressure)
                )
                new_notes.append(note_spec)
                
                pos += note_spacing
            
            # Add all fill notes using Live 12 API
            if len(new_notes) > 0:
                clip.add_new_notes(tuple(new_notes))
                self._log("Filled drum %d with %d %s (pitch %d) - other drums unaffected" % (drum_index, len(new_notes), pattern_name, pitch))
            else:
                self._log("No fill notes generated for drum %d" % drum_index)
            
            # Ensure clip detail remains visible
            try:
                self._ensure_clip_detail_visible(clip)
                if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                    clip.view.show_loop()
            except Exception:
                pass
        except Exception as e:
            try:
                self._log("Fill pattern error: " + str(e))
            except Exception:
                pass

    def _show_current_function_indicator(self):
        # Show the blink pattern for the currently selected function
        try:
            blink_count = self._function_indicator_patterns.get(self._current_function_color, 1)
            self._function_button_blink_target = blink_count
            self._function_button_blink_count = 0
            self._function_button_blink_phase = 0
        except Exception:
            pass

    def _sync_knob_leds(self):
        # Light assignable knobs to reflect per-mode buffers
        try:
            # Use internal shift state tracking instead of is_pressed property
            shift_pressed = getattr(self, '_shift_is_pressed', False)
            for i in range(min(len(self._knob_controls), len(self._assignable_knob_values))):
                # Use per-mode values to display distinct rings
                if shift_pressed and i < len(self._assignable_knob_slide_values):
                    val = max(0, min(127, int(self._assignable_knob_slide_values[i])))
                elif (not shift_pressed) and i < len(self._assignable_knob_pitch_values):
                    val = max(0, min(127, int(self._assignable_knob_pitch_values[i])))
                else:
                    val = max(0, min(127, int(self._assignable_knob_values[i])))
                self._cs._send_midi((0xB0 | 0, 56 + i, val))
        except Exception:
            pass
        # Light device control knobs to reflect current per-drum buffers
        try:
            idx = max(0, min(len(self._drum_velocity) - 1, int(self._selected_drum)))
            # Expect first two device knobs to map: 0 -> pressure, 1 -> velocity (adjust if mapped differently)
            # Use internal shift state tracking instead of is_pressed property
            shift_pressed = getattr(self, '_shift_is_pressed', False)
            for i, _ in enumerate(self._device_controls):
                if i == 0:
                    # Device knob 1 shows Pressure (no shift) or Velocity (with shift) to reflect editing target
                    val = int(self._drum_velocity[idx]) if shift_pressed else int(self._drum_pressure[idx])
                elif i == 1:
                    # Device knob 2 mirrors the complementary buffer for visibility
                    val = int(self._drum_pressure[idx]) if shift_pressed else int(self._drum_velocity[idx])
                else:
                    continue
                self._cs._send_midi((0xB0 | 0, 24 + i, max(0, min(127, val))))
        except Exception:
            pass
