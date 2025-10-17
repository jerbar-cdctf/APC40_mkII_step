from __future__ import absolute_import, print_function, unicode_literals
import Live

class StepSequencer(object):
    def __init__(self, control_surface, song, shift_button, user_button, pan_button, sends_button,
                 left_button, right_button, up_button, down_button,
                 scene_launch_buttons_raw, clip_stop_buttons_raw, matrix_rows_raw, knob_controls, track_select_buttons,
                 device_controls=None, prev_device_button=None, next_device_button=None):
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
        self._note_lengths = [0.25, 0.5, 1.0, 2.0, 4.0]  # 1/16 .. 1 bar (in beats)
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
        self._LED_BLUE = 45

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
            # Scene launch buttons are unused in sequencer mode now (loop length moved to clip stop)
            # We leave listeners detached
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
            # Initial render of note length LEDs on track select buttons
            try:
                self._render_note_length_leds()
            except Exception:
                pass
        except Exception:
            pass

    def _on_shift_value(self, value):
        # Momentary shift: pressed when value > 0, otherwise not pressed.
        # Do not latch any internal state; always query is_pressed at use-time.
        try:
            pressed = bool(value)
            try:
                self._cs.log_message("Shift %s" % ("pressed" if pressed else "released"))
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
        
        if slot and slot.has_clip:
            try:
                clip = slot.clip
                # Test if logging works in this context
                try:
                    self._cs.log_message("Grid refresh - found clip")
                except Exception as log_error:
                    # If logging fails, continue anyway
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
                loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
                if start >= loop_length:
                    self._set_pad_led_color(c, r, 0)
                    continue
                if clip is None:
                    self._set_pad_led_color(c, r, 0)
                    continue
                try:
                    # Use Live 11 API for note lookup
                    search_start = max(0, start - 0.001)
                    search_duration = note_len + 0.002
                    if hasattr(clip, 'get_notes_extended'):
                        # get_notes_extended(from_pitch, pitch_span, from_time, time_span)
                        existing = clip.get_notes_extended(pitch, 1, search_start, search_duration)
                    else:
                        # Old API: get_notes(from_time, from_pitch, time_span, pitch_span)
                        existing = clip.get_notes(search_start, pitch, search_duration, 1)
                    if existing and len(existing) > 0:
                        note_count += 1
                except Exception:
                    existing = []
                has_note = bool(existing and len(existing) > 0)
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

    def _enter(self):
        self._mode = True
        # Log sequencer state for debugging
        try:
            self._cs.log_message("=== Sequencer Enter ===")
            self._cs.log_message("time_page: " + str(self._time_page) + " drum_row_base: " + str(self._drum_row_base))
            self._cs.log_message("note_length_index: " + str(self._note_length_index) + " loop_bars_index: " + str(self._loop_bars_index))
            slot = self._current_clip_slot()
            if slot:
                self._cs.log_message("Clip slot found - has_clip: " + str(slot.has_clip))
                if slot.has_clip:
                    try:
                        clip = slot.clip
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
    def _exit(self):
        self._mode = False

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
        self._time_page += 1
        try:
            self._cs.log_message("Right pressed - time_page now: " + str(self._time_page))
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
        shift_pressed = False
        try:
            # Many ButtonElements expose is_pressed as a property
            shift_pressed = bool(getattr(self._shift_button, 'is_pressed', False))
        except Exception:
            shift_pressed = False
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
        shift_pressed = False
        try:
            shift_pressed = bool(getattr(self._shift_button, 'is_pressed', False))
        except Exception:
            shift_pressed = False
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
            self._note_length_index = track_index
            try:
                self._cs.log_message("Track select " + str(track_index) + " changed note length to " + str(self._note_lengths[track_index]) + " beats")
            except Exception:
                pass
            # Update LEDs to reflect the current selection
            try:
                self._render_note_length_leds()
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
        try:
            shift_pressed = bool(getattr(self._shift_button, 'is_pressed', False))
        except Exception:
            shift_pressed = False

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

    def _enter(self):
        # Called by control surface when entering sequencer mode
        self._mode = True
        try:
            self._render_note_length_leds()
        except Exception:
            pass

    def _exit(self):
        # Called by control surface when exiting sequencer mode
        self._mode = False
        try:
            self._clear_note_length_leds()
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
        if start >= loop_length:
            return
        # Check for existing notes - use Live 11 API
        # get_notes_extended(from_pitch, pitch_span, from_time, time_span)
        try:
            search_start = max(0, start - 0.001)
            search_duration = note_len + 0.002
            # Use Live 11 API if available, fallback to old API
            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(pitch, 1, search_start, search_duration)
            else:
                # Old API: get_notes(from_time, from_pitch, time_span, pitch_span)
                existing = clip.get_notes(search_start, pitch, search_duration, 1)
            try:
                self._cs.log_message("Button pressed - pitch: " + str(pitch) + " start: " + str(start) + " len: " + str(note_len) + " found: " + str(len(existing)) + " notes")
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
            try:
                # Write the note using supported APIs (Lite may not support per-note expressions)
                if hasattr(clip, 'add_new_notes'):
                    note_spec = Live.Clip.MidiNoteSpecification(pitch=int(pitch), start_time=float(start), duration=float(note_len), velocity=int(velocity), mute=False, release_velocity=int(mpe_pressure))
                    clip.add_new_notes((note_spec,))
                else:
                    # Fallback to legacy API if necessary
                    clip.set_notes(((float(start), int(pitch), float(note_len), int(velocity), False),))
                self._cs.log_message("Note added - pitch: " + str(pitch) + " time: " + str(start) + " duration: " + str(note_len) + " velocity: " + str(velocity) + " mpe: " + str(mpe_pressure))
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
        track = song.view.selected_track
        scene = song.view.selected_scene
        scenes = list(song.scenes)
        try:
            scene_index = scenes.index(scene)
        except ValueError:
            return None
        try:
            return track.clip_slots[scene_index]
        except Exception:
            return None

    def _ensure_clip(self):
        slot = self._current_clip_slot()
        if slot is None:
            return None
        if not slot.has_clip:
            bars = self._loop_bars_options[self._loop_bars_index]
            length = bars * 4.0
            try:
                slot.create_clip(length)
            except Exception:
                return None
        try:
            clip = slot.clip
            # Verify it's a MIDI clip
            if clip and hasattr(clip, 'is_midi_clip') and clip.is_midi_clip:
                return clip
            elif clip and hasattr(clip, 'get_notes'):
                # Fallback: if it has get_notes, assume MIDI
                return clip
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
        except Exception:
            pass
        try:
            if hasattr(clip, 'remove_notes_extended'):
                # remove any notes starting after the new loop end across full pitch range
                clip.remove_notes_extended(0, 128, new_end, 9999.0)
            else:
                clip.remove_notes(new_end, 9999.0, 0, 127)
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

    # Blinking playhead
    def _schedule_tick(self):
        try:
            self._cs.schedule_message(2, self._tick)  # ~30ms*2 per tick (approx), adjust as needed
        except Exception:
            pass

    def _tick(self):
        if not self._mode:
            return
        self._update_blink()
        self._schedule_tick()

    def _update_blink(self):
        try:
            bars = self._loop_bars_options[self._loop_bars_index]
            loop_len = bars * 4.0
            note_len = self._note_lengths[self._note_length_index]
            pos = self._song.current_song_time % max(loop_len, 0.0001)
            step_idx = int(pos / max(note_len, 0.0001))
            col = step_idx % self._steps_per_page
        except Exception:
            col = None
        # restore previous column
        if self._last_blink_col is not None and self._last_blink_col != col:
            for r in range(len(self._matrix_rows_raw)):
                # redraw to actual note state
                self._redraw_cell(self._last_blink_col, r)
        # draw current column blink state
        if col is not None:
            self._blink_on = not self._blink_on
            for r in range(len(self._matrix_rows_raw)):
                try:
                    btn = self._matrix_rows_raw[r][col]
                    if self._blink_on:
                        btn.turn_on()  # ideally this would be red; using default on as fallback
                    else:
                        self._redraw_cell(col, r)
                except Exception:
                    pass
        self._last_blink_col = col

    def _redraw_cell(self, col, row):
        pitch = self._row_note_offsets[row + self._drum_row_base]
        step = col + self._time_page * self._steps_per_page
        note_len = self._note_lengths[self._note_length_index]
        start = step * note_len
        clip = self._ensure_clip()
        if clip is None or start >= self._loop_bars_options[self._loop_bars_index] * 4.0:
            self._set_pad_led_color(col, row, 0)
            return
        try:
            # Prefer Live 12 extended API when available
            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(pitch, 1, start, note_len)
            else:
                existing = clip.get_notes(start, pitch, note_len, 1)
        except Exception:
            existing = []
        has_note = bool(existing)
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

    def _update_selected_drum_notes(self, velocity=None, release_velocity=None):
        # Use Live 12 API to modify existing notes for the selected drum (pitch at selected row)
        clip = self._ensure_clip()
        if clip is None:
            return
        try:
            pitch = self._row_note_offsets[self._selected_drum]
        except Exception:
            return
        loop_len = 0.0
        try:
            loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
        except Exception:
            loop_len = 0.0
        try:
            if hasattr(clip, 'get_notes_extended') and hasattr(clip, 'apply_note_modifications'):
                notes = clip.get_notes_extended(pitch, 1, 0.0, max(loop_len, 0.0001))
                if not notes:
                    return
                # Debug: log before values for first few notes
                try:
                    preview = notes[:4]
                    for n in preview:
                        self._cs.log_message("Before mod pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
                except Exception:
                    pass
                for n in notes:
                    if velocity is not None:
                        n.velocity = int(max(1, min(127, int(velocity))))
                    if release_velocity is not None and hasattr(n, 'release_velocity'):
                        n.release_velocity = int(max(0, min(127, int(release_velocity))))
                clip.apply_note_modifications(notes)
                # Debug: log after values for first few notes
                try:
                    preview = notes[:4]
                    for n in preview:
                        self._cs.log_message("After mod pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
                except Exception:
                    pass
        except Exception as e:
            try:
                self._cs.log_message("apply_note_modifications error: " + str(e))
            except Exception:
                pass

    def _current_step_window(self):
        # Returns (pitch, from_time, time_span) for the precise current step selection
        clip = self._ensure_clip()
        if clip is None:
            raise RuntimeError("No clip")
        # Determine column priority: last pad press > blinking playhead > 0
        if getattr(self, '_last_interacted_col', None) is not None:
            col = int(self._last_interacted_col)
        elif getattr(self, '_last_blink_col', None) is not None:
            col = int(self._last_blink_col)
        else:
            col = 0
        step = int(col) + int(self._time_page) * int(self._steps_per_page)
        note_len = float(self._note_lengths[self._note_length_index])
        start = float(step) * note_len
        from_time = max(0.0, start + 0.000)
        time_span = min(note_len, 0.010)
        pitch = int(self._row_note_offsets[self._selected_drum])
        # Log window
        try:
            self._cs.log_message("Step window col=%d pitch=%d from=%.5f span=%.5f" % (int(col), int(pitch), float(from_time), float(time_span)))
        except Exception:
            pass
        return (pitch, from_time, time_span)

    def _update_step_notes(self, pitch, from_time, time_span, velocity=None, release_velocity=None):
        # Modify only notes within a precise step window
        clip = self._ensure_clip()
        if clip is None:
            return
        if not hasattr(clip, 'get_notes_extended') or not hasattr(clip, 'apply_note_modifications'):
            # Fall back to entire row update if precise window not supported
            self._update_selected_drum_notes(velocity=velocity, release_velocity=release_velocity)
            return
        try:
            notes = clip.get_notes_extended(from_pitch=int(pitch), pitch_span=1, from_time=float(from_time), time_span=float(time_span))
            try:
                self._cs.log_message("Step notes found=%d for pitch=%d" % (len(notes) if notes else 0, int(pitch)))
            except Exception:
                pass
            if not notes:
                return
            # Log before values
            try:
                preview = notes[:4]
                for n in preview:
                    self._cs.log_message("Step Before pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
            except Exception:
                pass
            for n in notes:
                if velocity is not None:
                    n.velocity = int(max(1, min(127, int(velocity))))
                if release_velocity is not None and hasattr(n, 'release_velocity'):
                    n.release_velocity = int(max(0, min(127, int(release_velocity))))
            clip.apply_note_modifications(notes)
            # Log after values
            try:
                preview = notes[:4]
                for n in preview:
                    self._cs.log_message("Step After  pitch=%d start=%.5f dur=%.5f vel=%d rel_vel=%s" % (int(n.pitch), float(n.start_time), float(n.duration), int(getattr(n, 'velocity', -1)), str(getattr(n, 'release_velocity', 'n/a'))))
            except Exception:
                pass
        except Exception as e:
            try:
                self._cs.log_message("update_step_notes error: " + str(e))
            except Exception:
                pass

    def _sync_knob_leds(self):
        # Light assignable knob ring LEDs with last values per current mode (CC 56-63)
        try:
            shift_pressed = False
            try:
                shift_pressed = bool(getattr(self._shift_button, 'is_pressed', False))
            except Exception:
                shift_pressed = False
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
            shift_pressed = False
            try:
                shift_pressed = bool(getattr(self._shift_button, 'is_pressed', False))
            except Exception:
                shift_pressed = False
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
