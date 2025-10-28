from __future__ import absolute_import, print_function, unicode_literals
import Live

class StepSequencer(object):
    def __init__(self, control_surface, song, shift_button, user_button, pan_button, sends_button,
                 left_button, right_button, up_button, down_button,
                 scene_launch_buttons_raw, clip_stop_buttons_raw, matrix_rows_raw, knob_controls, track_select_buttons,
                 device_controls=None, prev_device_button=None, next_device_button=None, 
                 stop_all_button=None, master_button=None):
        self._cs = control_surface
        self._song = song
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
        # 16 chromatic notes starting from C1 (MIDI 36) to D#2 (MIDI 51)
        # C1, C#1, D1, D#1, E1, F1, F#1, G1, G#1, A1, A#1, B1, C2, C#2, D2, D#2
        self._row_note_offsets = [36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51]
        self._drum_row_base = 0
        self._time_page = 0
        self._note_length_index = 0
        # Note lengths in beats: 1/2 bar, 8 bars, 4 bars, 2 bars, 1 bar, 1/4 bar, 1/8th bar, 1/16th bar
        self._note_lengths = [2.0, 32.0, 16.0, 8.0, 4.0, 1.0, 0.5, 0.25]
        self._loop_bars_options = [1, 2, 4, 8, 16]
        self._loop_bars_index = 0
        # Per-drum buffers (16 chromatic rows starting at C1)
        self._drum_velocity = [64] * 16  # 0-127
        self._drum_pressure = [0] * 16   # 0-127
        self._selected_drum = 0          # index into _row_note_offsets (0..15)
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
                    self._cs.log_message("StepSequencer: Stop All button listener registered")
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
                self._cs.log_message("Shift %s" % ("pressed" if self._shift_is_pressed else "released"))
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
        clip = self._ensure_clip()
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
                self._cs.log_message("Select window col=%d pitch=%d from=%.5f span=%.5f caps=%s" % (int(col), int(pitch), float(from_time), float(time_span), str(caps)))
            except Exception:
                pass
            # Prefer Live 12 extended selection API if available; select exact notes at this step
            if hasattr(clip, 'get_notes_extended') and hasattr(clip, 'select_notes_extended'):
                # First, find the notes in this step window
                step_notes = clip.get_notes_extended(from_pitch=pitch, pitch_span=1, from_time=from_time, time_span=time_span)
                try:
                    self._cs.log_message("Found %d notes in step window" % (len(step_notes) if step_notes else 0))
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
                            self._cs.log_message("Selected note pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
                        except Exception:
                            pass
                    except Exception:
                        continue
            else:
                # Fallback: selection API not available; skip broad select to avoid row-wide edits
                try:
                    self._cs.log_message("select_notes_extended unavailable; skipping selection fallback to avoid selecting entire row")
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
            self._cs.log_message("=== GRID REFRESH START ===")
            self._cs.log_message("Note length: %.2f beats (index %d)" % (self._note_lengths[self._note_length_index], self._note_length_index))
            self._cs.log_message("Time page: %d, Drum base: %d" % (self._time_page, self._drum_row_base))
            self._cs.log_message("Loop: %d bars = %.1f beats" % (self._loop_bars_options[self._loop_bars_index], self._loop_bars_options[self._loop_bars_index] * 4.0))
        except Exception:
            pass
        
        if slot and slot.has_clip:
            try:
                clip = slot.clip
                try:
                    self._cs.log_message("Grid refresh - found clip")
                except Exception:
                    pass
            except Exception:
                pass
        
        for r in range(len(self._matrix_rows_raw)):
            for c in range(min(self._steps_per_page, len(self._matrix_rows_raw[r]))):
                row_offset = r + self._drum_row_base
                if row_offset >= len(self._row_note_offsets):
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
                if row_offset == self._selected_drum:
                    # Selected row: green when active, blue when empty
                    color = self._LED_GREEN if has_note else self._LED_BLUE
                    self._set_pad_led_color(c, r, color)
                else:
                    # Other rows: green when active, off when empty
                    color = self._LED_GREEN if has_note else 0
                    self._set_pad_led_color(c, r, color)
        
        # Log summary after refresh - use try/except for safety
        try:
            self._cs.log_message("Grid refresh complete - found " + str(note_count) + " notes to display")
        except Exception:
            pass
        # Update scene function LEDs to reflect current drum view
        try:
            self._render_scene_function_leds()
        except Exception:
            pass

    def _enter(self):
        self._mode = True
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
                    self._cs.log_message("No notes detected - initializing to 1 bar, 1/4 note resolution")
                except Exception:
                    pass
                # CRITICAL: Actually apply the 1 bar loop to the clip so it doesn't play forever
                try:
                    self._apply_loop_length()
                    self._cs.log_message("Applied 1 bar loop length to blank clip")
                except Exception as e:
                    try:
                        self._cs.log_message("Failed to apply loop length to blank clip: " + str(e))
                    except Exception:
                        pass
        except Exception as e:
            try:
                self._cs.log_message("Note detection error: " + str(e))
            except Exception:
                pass
        
        # Update current tempo on entry for immediate accuracy
        try:
            if hasattr(self._song, 'tempo'):
                self._current_tempo = float(self._song.tempo)
        except Exception:
            pass
        
        # Log sequencer state for debugging
        try:
            self._cs.log_message("=== Sequencer Enter ===")
            self._cs.log_message("Tempo: %.1f BPM" % self._current_tempo)
            self._cs.log_message("time_page: " + str(self._time_page) + " drum_row_base: " + str(self._drum_row_base))
            self._cs.log_message("note_length_index: " + str(self._note_length_index) + " loop_bars_index: " + str(self._loop_bars_index))
            # Calculate and log the tick interval
            tick_interval = self._calculate_tick_interval()
            update_rate_ms = tick_interval * 30
            self._cs.log_message("Playhead update rate: every %d ticks (~%dms) for %.1f BPM" % (tick_interval, update_rate_ms, self._current_tempo))
            slot = self._current_clip_slot()
            if slot:
                self._cs.log_message("Clip slot found - has_clip: " + str(slot.has_clip))
                if slot.has_clip:
                    try:
                        clip = slot.clip
                        # Log which clip we're viewing
                        try:
                            track_name = self._song.view.selected_track.name if hasattr(self._song.view.selected_track, 'name') else 'Unknown'
                            scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
                            clip_name = clip.name if hasattr(clip, 'name') else 'Unnamed'
                            self._cs.log_message("Viewing clip: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
                        except Exception:
                            pass
                        self._cs.log_message("Clip is_midi_clip: " + str(clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else 'N/A'))
                    except Exception as e:
                        self._cs.log_message("Error accessing clip: " + str(e))
            else:
                self._cs.log_message("No clip slot found")
        except Exception as e:
            try:
                self._cs.log_message("Sequencer enter logging error: " + str(e))
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
            self._cs.log_message("Refreshing grid for current clip...")
            self._refresh_grid()
        except Exception as e:
            try:
                self._cs.log_message("Grid refresh on enter failed: " + str(e))
            except Exception:
                pass
        # CRITICAL: Start playhead tracking by scheduling first tick
        try:
            self._schedule_tick()
            self._cs.log_message("Playhead tracking started")
        except Exception as e:
            try:
                self._cs.log_message("Failed to start playhead tracking: " + str(e))
            except Exception:
                pass
    
    def _exit(self):
        self._mode = False
        # CRITICAL: Clear all LEDs to prevent carryover to next session
        try:
            self._cs.log_message("Clearing all LEDs on exit...")
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
            self._cs.log_message("State variables reset to defaults")
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
                self._cs.log_message("Left pressed - time_page now: " + str(self._time_page))
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
                    self._cs.log_message("Right pressed - time_page now: %d (max: %d)" % (self._time_page, max_page))
                except Exception:
                    pass
            else:
                try:
                    self._cs.log_message("Already at end of loop (page %d of %d)" % (self._time_page, max_page))
                except Exception:
                    pass
        except Exception:
            # Fallback: allow navigation but log error
            self._time_page += 1
            try:
                self._cs.log_message("Right pressed (fallback) - time_page now: " + str(self._time_page))
            except Exception:
                pass
        self._refresh_grid()

    def _on_up(self, value):
        if not value or not self._mode:
            return
        if self._drum_row_base > 0:
            self._drum_row_base -= 1
            try:
                self._cs.log_message("Up pressed - drum_row_base now: " + str(self._drum_row_base))
            except Exception:
                pass
            self._refresh_grid()

    def _on_down(self, value):
        if not value or not self._mode:
            return
        # Allow scrolling through all drum notes in groups of 5
        max_base = len(self._row_note_offsets) - self._rows_visible
        if self._drum_row_base < max_base:
            self._drum_row_base += 1
            try:
                self._cs.log_message("Down pressed - drum_row_base now: " + str(self._drum_row_base))
            except Exception:
                pass
            self._refresh_grid()
    def _on_knob_value(self, knob_index, value, sender=None):
        if not self._mode:
            return
        # Use internal shift state tracking instead of is_pressed property
        shift_pressed = getattr(self, '_shift_is_pressed', False)
        # Debug: log assignable knob intent
        try:
            self._cs.log_message("Assignable knob %d value=%d mode=%s" % (int(knob_index), int(value), ("Slide(CC74)" if shift_pressed else "PitchBend")))
        except Exception:
            pass
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
            self._cs.log_message("Device knob %d value=%d target=%s drum=%d" % (int(knob_index), int(value), ("Velocity" if shift_pressed else "Pressure(release_velocity)"), int(idx)))
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
                self._cs.log_message("=== NOTE LENGTH CHANGE ===")
                self._cs.log_message("Track button %d pressed" % track_index)
                self._cs.log_message("Old: index=%d length=%.2f beats" % (old_index, old_length))
                self._cs.log_message("New: index=%d length=%.2f beats" % (track_index, new_length))
                self._cs.log_message("Mode active: %s" % str(self._mode))
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
            # Refresh grid to show notes at new step size
            try:
                self._cs.log_message("Refreshing grid after note length change...")
                self._refresh_grid()
                self._cs.log_message("Grid refresh completed")
            except Exception as e:
                try:
                    self._cs.log_message("Grid refresh error: " + str(e))
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
                self._cs.log_message("Loop length changed to " + str(options[index]) + " bars" + (" (shift mode)" if shift_pressed else ""))
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
                    self._cs.log_message("Reset time_page to 0 (was beyond new loop length)")
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
                    self._cs.log_message("Applied clip loop: start=%.2f end=%.2f (bars=%d)" % (start, start + beats, bars))
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
                    self._cs.log_message("Applied arrangement loop: start=%.2f length=%.2f" % (float(song.loop_start), float(song.loop_length)))
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
                self._cs.log_message("Rainbow animation cancelled by grid button press")
                # Refresh will happen after note is added/removed below
            except Exception:
                pass
        
        # remember the last step interacted with for precise selection
        try:
            self._last_interacted_col = int(col)
        except Exception:
            pass
        # All rows are now available for note input
        row_offset = row + self._drum_row_base
        if row_offset >= len(self._row_note_offsets):
            return
        pitch = self._row_note_offsets[row_offset]
        step = col + self._time_page * self._steps_per_page
        clip = self._ensure_clip()
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
                self._cs.log_message("=== MATRIX BUTTON PRESSED ===")
                # Log which clip is being modified
                try:
                    track_name = self._song.view.selected_track.name if hasattr(self._song.view.selected_track, 'name') else 'Unknown'
                    scene_index = list(self._song.scenes).index(self._song.view.selected_scene)
                    clip_name = clip.name if hasattr(clip, 'name') else 'Unnamed'
                    self._cs.log_message("Target: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
                except Exception:
                    pass
                self._cs.log_message("Position: col=%d row=%d" % (col, row))
                self._cs.log_message("Pitch: %d, Step: %d" % (pitch, step))
                self._cs.log_message("Note length: %.2f beats (index %d)" % (note_len, self._note_length_index))
                self._cs.log_message("Start: %.6f, Search: %.6f-%.6f" % (start, search_start, search_start + search_duration))
                self._cs.log_message("Found: %d notes" % (len(existing) if existing else 0))
                if existing and len(existing) > 0:
                    self._cs.log_message("  First note: " + str(existing[0]))
            except Exception:
                pass
        except Exception as e:
            existing = []
            try:
                self._cs.log_message("get_notes error: " + str(e))
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
                    self._cs.log_message("Removing note - pitch: " + str(note_pitch) + " time: " + str(note_time) + " duration: " + str(note_duration))
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
                    row_offset = row + self._drum_row_base
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
                    self._cs.log_message("Remove failed: " + str(e))
                except Exception:
                    pass
            # Do not force turn-off here; pad state already updated above
        else:
            # Add note with per-drum velocity/pressure buffers
            drum_index = row_offset
            velocity = int(self._drum_velocity[drum_index])
            mpe_pressure = int(self._drum_pressure[drum_index])
            # Clip note duration if it would extend beyond loop end
            actual_note_len = note_len
            if start + note_len > loop_length:
                actual_note_len = max(0.01, loop_length - start)  # Minimum 0.01 beat duration
                try:
                    self._cs.log_message("Note clipped: original len=%.2f, clipped to %.2f (loop end at %.2f)" % (note_len, actual_note_len, loop_length))
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
                self._cs.log_message("Note added - pitch: " + str(pitch) + " time: " + str(start) + " duration: " + str(actual_note_len) + " velocity: " + str(velocity) + " mpe: " + str(mpe_pressure))
            except Exception as e:
                try:
                    self._cs.log_message("Note add failed (fallback): " + str(e))
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
            self._cs.log_message("Selected drum index: " + str(self._selected_drum))
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
                drum_index = self._drum_row_base + i
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
                                self._cs.log_message("Scene button %d (drum %d): showing function color %d" % (i, drum_index, color))
                        except Exception:
                            color = 0
                try:
                    btn.send_value(color, True)
                except Exception:
                    pass
            if assignments_found == 0:
                self._cs.log_message("No drum function assignments found - all scene buttons turned off")
            else:
                self._cs.log_message("Rendered %d drum function assignments on scene buttons" % assignments_found)
        except Exception as e:
            self._cs.log_message("Error in _render_scene_function_leds: %s" % str(e))

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
            track = song.view.selected_track
            scene = song.view.selected_scene
            scenes = list(song.scenes)
            scene_index = scenes.index(scene)
            
            # Log debug info
            track_name = track.name if hasattr(track, 'name') else 'Unknown'
            self._cs.log_message("_current_clip_slot: Track='%s' Scene=%d" % (track_name, scene_index))
            
            slot = track.clip_slots[scene_index]
            return slot
        except Exception as e:
            self._cs.log_message("_current_clip_slot error: %s" % str(e))
            return None

    def _ensure_clip(self):
        slot = self._current_clip_slot()
        if slot is None:
            try:
                self._cs.log_message("ERROR: _ensure_clip - no clip slot found")
            except Exception:
                pass
            return None
        if not slot.has_clip:
            bars = self._loop_bars_options[self._loop_bars_index]
            length = bars * 4.0
            try:
                self._cs.log_message("Creating new clip with length %.1f beats" % length)
                slot.create_clip(length)
            except Exception as e:
                try:
                    self._cs.log_message("ERROR: Failed to create clip: " + str(e))
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
                self._cs.log_message("Accessing clip: Track='%s' Scene=%d Clip='%s'" % (track_name, scene_index, clip_name))
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
                    self._cs.log_message("ERROR: Clip is not a MIDI clip or doesn't have get_notes")
                except Exception:
                    pass
        except Exception as e:
            try:
                self._cs.log_message("ERROR: Exception accessing clip: " + str(e))
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
                self._cs.log_message("Tempo changed to: %.1f BPM" % self._current_tempo)
            except Exception:
                pass
        except Exception:
            pass

    def _calculate_tick_interval(self):
        """Calculate optimal tick interval based on tempo and note length.
        Returns number of schedule_message ticks (~30ms each) for smooth playhead tracking."""
        try:
            # Get current tempo (BPM) and note length (beats)
            tempo = max(20.0, min(999.0, float(self._current_tempo)))  # Clamp to reasonable range
            note_len = float(self._note_lengths[self._note_length_index])
            
            # Calculate time per note in seconds: (60 seconds/minute) / (tempo beats/minute) * note_length_beats
            seconds_per_note = (60.0 / tempo) * note_len
            
            # Target: update at least 8-10 times per note for smooth tracking
            # At 180 BPM with 1/16 notes (0.25 beats): 0.083s per note -> ~8ms updates
            # At 120 BPM with 1/4 notes (1.0 beats): 0.5s per note -> ~50ms updates
            target_updates_per_note = 10.0
            update_interval_seconds = seconds_per_note / target_updates_per_note
            
            # Convert to schedule_message ticks (~30ms per tick)
            # Minimum 1 tick (30ms) for fastest updates, maximum 3 ticks (90ms) for slower tempos
            tick_interval = max(1, min(3, int(round(update_interval_seconds / 0.030))))
            
            return tick_interval
        except Exception:
            return 2  # Fallback to reasonable default

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
            self._cs.log_message("Starting rainbow animation: note length=%.2f beats, max duration=%.1f beats" % (note_len, self._animation_max_duration_beats))
        except Exception as e:
            try:
                self._cs.log_message("Animation trigger error: " + str(e))
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
                        self._cs.log_message("Rainbow animation ended (%.1f beats elapsed)" % elapsed_beats)
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
                self._cs.log_message("Error in _enter: " + str(e))
            except Exception:
                pass
        
        # CRITICAL: Refresh grid and ensure playhead tracking continues
        try:
            self._refresh_grid()
            self._schedule_tick()
            self._cs.log_message("Grid refreshed and playhead tracking started")
        except Exception as e:
            try:
                self._cs.log_message("Error refreshing grid in _enter: " + str(e))
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
        # Always run playhead tracking regardless of mode
        # Run animation if active (takes priority over playhead blink)
        if self._animation_active:
            try:
                self._animate_note_length()
            except Exception:
                pass
        else:
            # Normal playhead blinking when not animating
            self._update_blink()
        
        # Always update display for scene preview and other UI elements
        try:
            self._update_display()
        except Exception:
            pass
        
        self._schedule_tick()

    def _update_blink(self):
        try:
            bars = self._loop_bars_options[self._loop_bars_index]
            loop_len = bars * 4.0
            note_len = self._note_lengths[self._note_length_index]
            
            # CRITICAL: Get accurate playhead position from clip, not just song time
            # Use clip.playing_position (Live 11+) for precise position within loop
            pos = 0.0
            try:
                clip = self._ensure_clip()
                if clip and hasattr(clip, 'playing_position'):
                    # Live 11+ API: playing_position gives position within the clip loop (0 to loop_end - loop_start)
                    pos = float(clip.playing_position)
                elif clip and hasattr(clip, 'loop_start'):
                    # Fallback: calculate position relative to loop_start
                    clip_start = float(clip.loop_start)
                    song_pos = float(self._song.current_song_time)
                    pos = (song_pos - clip_start) % max(loop_len, 0.0001)
                else:
                    # Last resort: use song time
                    pos = self._song.current_song_time % max(loop_len, 0.0001)
            except Exception as e:
                # Fallback to song time if clip access fails
                pos = self._song.current_song_time % max(loop_len, 0.0001)
                try:
                    self._cs.log_message("Playhead position fallback: " + str(e))
                except Exception:
                    pass
            
            step_idx = int(pos / max(note_len, 0.0001))
            col = step_idx % self._steps_per_page
            # Update loop position indicator on clip stop buttons
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
            except Exception:
                pass
            
            # Log playhead position for debugging (reduced frequency to avoid spam)
            try:
                if step_idx % 8 == 0:  # Log every 8 steps for verification
                    tick_interval = self._calculate_tick_interval()
                    # Also log comparison with song time to verify accuracy
                    try:
                        clip = self._ensure_clip()
                        song_time = float(self._song.current_song_time)
                        method = "unknown"
                        if clip and hasattr(clip, 'playing_position'):
                            method = "clip.playing_position"
                        elif clip and hasattr(clip, 'loop_start'):
                            method = "song_time - loop_start"
                        else:
                            method = "song_time (fallback)"
                        self._cs.log_message("Playhead [%s]: pos=%.3f song_time=%.3f step=%d col=%d page=%d note_len=%.2f tempo=%.1f" % (method, pos, song_time, step_idx, col, step_idx // self._steps_per_page, note_len, self._current_tempo))
                    except Exception:
                        self._cs.log_message("Playhead: pos=%.3f step=%d col=%d page=%d note_len=%.2f tempo=%.1f tick=%d" % (pos, step_idx, col, step_idx // self._steps_per_page, note_len, self._current_tempo, tick_interval))
            except Exception:
                pass
        except Exception as e:
            col = None
            try:
                self._cs.log_message("Blink calc error: " + str(e))
            except Exception:
                pass
        
        # Only update when column changes to prevent double-blinks
        if col != self._last_blink_col:
            # Restore previous column to normal state
            if self._last_blink_col is not None:
                for r in range(len(self._matrix_rows_raw)):
                    self._redraw_cell(self._last_blink_col, r)
            
            # Flash new column once
            if col is not None:
                self._blink_phase = 0  # Reset phase counter
                for r in range(len(self._matrix_rows_raw)):
                    try:
                        # Check if there's a note at this position
                        row_offset = r + self._drum_row_base
                        if row_offset >= len(self._row_note_offsets):
                            continue
                        pitch = self._row_note_offsets[row_offset]
                        step = col + self._time_page * self._steps_per_page
                        start = step * note_len
                        clip = self._ensure_clip()
                        has_note = False
                        if clip is not None and start < loop_len:
                            try:
                                has_note = self._has_note_overlap_at(clip, pitch, float(start), float(note_len))
                            except Exception:
                                has_note = False
                        
                        # Highlight only notes in the playhead column; leave empties unchanged
                        if has_note:
                            self._set_pad_led_color(col, r, self._LED_YELLOW)  # Yellow for note under playhead
                    except Exception:
                        pass
        else:
            # Same column - increment phase and toggle display every N ticks for a slower blink
            if col is not None:
                self._blink_phase = (self._blink_phase + 1) % 6  # Toggle every ~6 ticks (~180ms)
                if self._blink_phase == 3:  # Turn off halfway through
                    for r in range(len(self._matrix_rows_raw)):
                        self._redraw_cell(self._last_blink_col, r)
                elif self._blink_phase == 0:  # Turn on at start
                    for r in range(len(self._matrix_rows_raw)):
                        try:
                            row_offset = r + self._drum_row_base
                            if row_offset >= len(self._row_note_offsets):
                                continue
                            pitch = self._row_note_offsets[row_offset]
                            step = col + self._time_page * self._steps_per_page
                            start = step * note_len
                            clip = self._ensure_clip()
                            has_note = False
                            if clip is not None and start < loop_len:
                                try:
                                    has_note = self._has_note_overlap_at(clip, pitch, float(start), float(note_len))
                                except Exception:
                                    has_note = False
                            
                            if has_note:
                                self._set_pad_led_color(col, r, self._LED_YELLOW)
                        except Exception:
                            pass
        
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
                        self._cs.log_message("Error lighting scene buttons: " + str(e))
                    except Exception:
                        pass
                
                # Increment blink count every tick
                self._scene_preview_count += 1
                
                # Check if preview is complete
                if self._scene_preview_count >= self._scene_preview_target:
                    try:
                        self._cs.log_message("Scene preview complete - %d blinks done" % self._scene_preview_count)
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
                            self._cs.log_message("Stop All LED turned OFF")
                    except Exception:
                        pass
                    
                    # Now apply the function rotation
                    self._scene_preview_active = False
                    if self._pending_function_rotation:
                        try:
                            current_idx = self._function_colors.index(self._current_function_color)
                            next_idx = (current_idx + 1) % len(self._function_colors)
                            self._current_function_color = self._function_colors[next_idx]
                            self._cs.log_message("Function rotation applied: new color = %d" % self._current_function_color)
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
                            self._cs.log_message("Function now selected: %s" % func_name)
                        except Exception:
                            pass
                        # Update scene LEDs to show current function assignments
                        try:
                            self._render_scene_function_leds()
                        except Exception:
                            pass
            except Exception as e:
                try:
                    self._cs.log_message("Scene preview error: " + str(e))
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
        pitch = self._row_note_offsets[row + self._drum_row_base]
        step = col + self._time_page * self._steps_per_page
        note_len = self._note_lengths[self._note_length_index]
        start = step * note_len
        clip = self._ensure_clip()
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
        row_offset = row + self._drum_row_base
        if row_offset == self._selected_drum:
            color = self._LED_GREEN if has_note else self._LED_BLUE
        else:
            color = self._LED_GREEN if has_note else 0
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
                                self._cs.log_message("Scene button %d has no send_value method" % i)
                        except Exception as e:
                            self._cs.log_message("Error updating scene button %d: %s" % (i, str(e)))
                    
                    # Check if preview is complete
                    if self._scene_preview_count >= self._scene_preview_target:
                        self._scene_preview_active = False
                        self._cs.log_message("Scene preview completing after %d ticks" % self._scene_preview_count)
                        # Apply function rotation if pending
                        if self._pending_function_rotation:
                            old_color = self._current_function_color
                            self._current_function_color = self._scene_preview_color
                            self._pending_function_rotation = False
                            self._cs.log_message("Function rotation applied: %d -> %d" % (old_color, self._current_function_color))
                        # Update scene LEDs to show current assignments
                        try:
                            self._render_scene_function_leds()
                            self._cs.log_message("Scene LEDs updated to show current drum function assignments")
                        except Exception as e:
                            self._cs.log_message("Error updating scene LEDs: %s" % str(e))
                        self._cs.log_message("Scene preview complete - %d ticks done" % self._scene_preview_count)
                except Exception as e:
                    try:
                        self._cs.log_message("Scene preview error: " + str(e))
                    except Exception:
                        pass
        except Exception as e:
            try:
                self._cs.log_message("Display update error: " + str(e))
            except Exception:
                pass

    def _on_scene_launch_button(self, button_index, value):
        # Scene launch buttons cycle the function assignment per drum (0 -> RED -> YELLOW -> ... -> 0)
        if not value or not self._mode:
            return
        try:
            # Map button index to visible drum row
            drum_index = button_index + self._drum_row_base
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
            self._cs.log_message("Drum %d set function: %s" % (drum_index, func_name))
            
            # Update scene function LEDs to reflect current state
            try:
                self._render_scene_function_leds()
            except Exception:
                pass
        except Exception as e:
            try:
                self._cs.log_message("Scene launch button error: " + str(e))
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
                    self._cs.log_message("Function rotation applied immediately: new color = %d" % self._current_function_color)
                    func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                                 self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                                 self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                                 self._LED_GREEN: "FILL WHOLE"}
                    self._cs.log_message("Function now selected: %s" % func_names.get(self._current_function_color, "UNKNOWN"))
            
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
            self._cs.log_message("Cycling function: %s -> %s" % (current_func, next_func))
            
            # Do NOT turn Stop All LED on or blink it - as per user preference
            # Commented out: self._stop_all_button.send_value(self._LED_ORANGE, True)
            # Note: We do not use blinks on Stop All button to show function as per user request
            
            # Immediately update scene buttons to show the new function color
            try:
                for i in range(len(self._scene_launch_buttons_raw)):
                    if hasattr(self._scene_launch_buttons_raw[i], 'send_value'):
                        self._scene_launch_buttons_raw[i].send_value(next_color, True)
                        self._cs.log_message("Scene button %d updated to color %d" % (i, next_color))
                    else:
                        self._cs.log_message("Scene button %d has no send_value method" % i)
            except Exception as e:
                self._cs.log_message("Error updating scene buttons: %s" % str(e))
            
            # Set up scene preview: show scene buttons in the new function color briefly
            self._scene_preview_active = True
            self._scene_preview_color = next_color
            self._scene_preview_count = 0
            self._scene_preview_target = 5  # Short duration, ~0.5-1 second
            self._scene_preview_phase = 0
            self._pending_function_rotation = True
            
            self._cs.log_message("Scene display updated: showing color %s for %d ticks" % (next_func, self._scene_preview_target))
            self._cs.log_message("Current function before preview: %d, Next function: %d" % (self._current_function_color, next_color))
        except Exception as e:
            try:
                self._cs.log_message("Stop all button error: " + str(e))
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
            self._cs.log_message("Master button pressed - current function: %d (%s)" % (self._current_function_color, current_func_name))
            
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
                    self._cs.log_message("No drums assigned to function %d - error blink started" % self._current_function_color)
                except Exception:
                    pass
                return
            
            # Execute the function based on color
            func_names = {0: "NONE", self._LED_RED: "CLEAR", self._LED_YELLOW: "COPY", self._LED_ORANGE: "PASTE",
                         self._LED_BLUE: "MPE MARKER", self._LED_PURPLE: "FILL 1/4", 
                         self._LED_DARK_PURPLE: "FILL 1/8", self._LED_LIME: "FILL 1/16", 
                         self._LED_GREEN: "FILL WHOLE"}
            func_name = func_names.get(self._current_function_color, "UNKNOWN")
            self._cs.log_message("Executing %s on %d drums: %s" % (func_name, len(drums_to_execute), str(drums_to_execute)))
            
            if self._current_function_color == self._LED_RED:  # CLEAR
                for drum_idx in drums_to_execute:
                    try:
                        self._clear_drum_notes(drum_idx)
                    except Exception as e:
                        self._cs.log_message("Error clearing drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color == self._LED_YELLOW:  # COPY
                for drum_idx in drums_to_execute:
                    try:
                        self._copy_drum_notes(drum_idx)
                    except Exception as e:
                        self._cs.log_message("Error copying drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color == self._LED_ORANGE:  # PASTE
                for drum_idx in drums_to_execute:
                    try:
                        self._paste_drum_notes(drum_idx)
                    except Exception as e:
                        self._cs.log_message("Error pasting drum %d: %s" % (drum_idx, str(e)))
            elif self._current_function_color in [self._LED_PURPLE, self._LED_DARK_PURPLE, self._LED_LIME, self._LED_GREEN]:  # FILL
                duration = {self._LED_PURPLE: 1.0, self._LED_DARK_PURPLE: 0.5, self._LED_LIME: 0.25, self._LED_GREEN: 4.0}[self._current_function_color]
                for drum_idx in drums_to_execute:
                    try:
                        self._fill_drum_notes(drum_idx, duration)
                    except Exception as e:
                        self._cs.log_message("Error filling drum %d: %s" % (drum_idx, str(e)))
            
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
            
            # Blink Master button 3 times for success feedback
            try:
                self._master_blink_active = True
                self._master_blink_count = 0
                self._master_blink_target = 3  # 3 blinks for success
                self._master_blink_phase = 0
                self._cs.log_message("Function %s executed on %d drums - success blink started" % (func_name, len(drums_to_execute)))
            except Exception:
                pass
            
            # Reset function to NONE after execution
            self._current_function_color = 0
            self._cs.log_message("Function reset to NONE after execution")
        except Exception as e:
            try:
                self._cs.log_message("Master button error: " + str(e))
            except Exception:
                pass
    
    def _clear_drum_notes(self, drum_index):
        # Clear all notes for the specified drum by directly removing all notes
        clip = self._ensure_clip()
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
            self._cs.log_message("Clearing drum %d (pitch %d) directly" % (drum_index, pitch))
            if hasattr(clip, 'remove_notes_extended'):
                clip.remove_notes_extended(pitch, 1, float(loop_start), float(loop_len))
            else:
                clip.remove_notes(float(loop_start), pitch, float(loop_len), 1)
            
            # Refresh entire grid to ensure consistency
            try:
                self._refresh_grid()
                self._cs.log_message("Grid refreshed after clearing drum %d" % drum_index)
            except Exception as e:
                self._cs.log_message("Error refreshing grid after clear: " + str(e))
            
            self._cs.log_message("Cleared all notes for drum %d (pitch %d)" % (drum_index, pitch))
        except Exception as e:
            try:
                self._cs.log_message("Clear drum notes error: " + str(e))
            except Exception:
                pass

    def _copy_drum_notes(self, drum_index):
        # Copy all notes for the specified drum to buffer
        clip = self._ensure_clip()
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
            
            self._cs.log_message("Copied %d notes from drum %d (pitch %d) - READ ONLY, source unchanged" % (len(self._copied_notes), drum_index, pitch))
        except Exception as e:
            try:
                self._cs.log_message("Copy drum notes error: " + str(e))
            except Exception:
                pass

    def _get_drum_notes(self, drum_index):
        clip = self._ensure_clip()
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
        clip = self._ensure_clip()
        if clip is None:
            return
        try:
            target_pitch = self._row_note_offsets[drum_index]
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
                self._cs.log_message("Pasted %d notes to drum %d (pitch %d) - other drums unaffected" % (len(new_notes), drum_index, target_pitch))
            else:
                self._cs.log_message("No valid notes to paste")
            
            # Ensure clip detail remains visible
            try:
                self._ensure_clip_detail_visible(clip)
                if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                    clip.view.show_loop()
            except Exception:
                pass
        except Exception as e:
            try:
                self._cs.log_message("Paste drum notes error: " + str(e))
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
        clip = self._ensure_clip()
        if clip is None:
            return
        
        try:
            pitch = self._row_note_offsets[drum_index]
            loop_len = self._loop_bars_options[self._loop_bars_index] * 4.0
            try:
                loop_start = float(getattr(clip, 'loop_start', 0.0))
            except Exception:
                loop_start = 0.0
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
                self._cs.log_message("Filled drum %d with %d %s (pitch %d) - other drums unaffected" % (drum_index, len(new_notes), pattern_name, pitch))
            else:
                self._cs.log_message("No fill notes generated for drum %d" % drum_index)
            
            # Ensure clip detail remains visible
            try:
                self._ensure_clip_detail_visible(clip)
                if hasattr(clip, 'view') and hasattr(clip.view, 'show_loop'):
                    clip.view.show_loop()
            except Exception:
                pass
        except Exception as e:
            try:
                self._cs.log_message("Fill pattern error: " + str(e))
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
