from __future__ import absolute_import, print_function, unicode_literals
import Live
from .SequencerBase import SequencerBase

class DrumSequencer(SequencerBase):
    """
    Drum-specific sequencer functionality.
    Handles drum rack detection, drum pad management, and drum-specific operations.
    """
    
    def __init__(self, control_surface, song, logger=None):
        """
        Initialize the drum sequencer.
        
        Args:
            control_surface: The main APC40 control surface instance
            song: The Live.Song.Song instance
            logger: Optional SequencerLogger instance
        """
        super(DrumSequencer, self).__init__(control_surface, song, logger)
        
        # Drum-specific state
        # Reversed to match Ableton: high notes at top, low notes at bottom
        self._row_note_offsets = [51, 50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37, 36]
        self._selected_drum = 0
        
        # Per-drum buffers for MPE values
        self._drum_velocity = [64] * 16
        self._drum_pressure = [0] * 16
        
        # Function system
        self._drum_functions = [0] * 16  # 0=none, 1=clear, 2=copy, 3=paste, etc.
        self._current_function = 0  # Currently selected function for master button
        self._copied_notes = None  # Buffer for copy/paste
        
        # Function color mapping
        self._FUNCTION_NONE = 0
        self._FUNCTION_CLEAR = 1
        self._FUNCTION_COPY = 2
        self._FUNCTION_PASTE = 3
        self._FUNCTION_MPE = 4
        self._FUNCTION_FILL_QUARTER = 5
        self._FUNCTION_FILL_EIGHTH = 6
        self._FUNCTION_FILL_SIXTEENTH = 7
        self._FUNCTION_FILL_WHOLE = 9
        self._FUNCTION_QUANT_TRIPLET = 10
        self._FUNCTION_QUANT_SEPTUPLET = 11
        
        self._function_colors = {
            self._FUNCTION_NONE: self._LED_OFF,
            self._FUNCTION_CLEAR: self._LED_RED,
            self._FUNCTION_COPY: self._LED_YELLOW,
            self._FUNCTION_PASTE: self._LED_ORANGE,
            self._FUNCTION_MPE: self._LED_BLUE,
            self._FUNCTION_FILL_QUARTER: self._LED_PURPLE,
            self._FUNCTION_FILL_EIGHTH: self._LED_DARK_PURPLE,
            self._FUNCTION_FILL_SIXTEENTH: self._LED_BROWN,
            self._FUNCTION_FILL_WHOLE: self._LED_DARK_BROWN,
            self._FUNCTION_QUANT_TRIPLET: self._LED_PINK,
            self._FUNCTION_QUANT_SEPTUPLET: self._LED_CYAN
        }
        
        self._function_names = {
            self._FUNCTION_NONE: "NONE",
            self._FUNCTION_CLEAR: "CLEAR",
            self._FUNCTION_COPY: "COPY",
            self._FUNCTION_PASTE: "PASTE",
            self._FUNCTION_MPE: "MPE_MARKER",
            self._FUNCTION_FILL_QUARTER: "FILL_QUARTER",
            self._FUNCTION_FILL_EIGHTH: "FILL_EIGHTH",
            self._FUNCTION_FILL_SIXTEENTH: "FILL_SIXTEENTH",
            self._FUNCTION_FILL_WHOLE: "FILL_WHOLE",
            self._FUNCTION_QUANT_TRIPLET: "QUANT_TRIPLET",
            self._FUNCTION_QUANT_SEPTUPLET: "QUANT_SEPTUPLET"
        }
        
        # Scene preview state
        self._scene_preview_active = False
        self._scene_preview_color = self._LED_OFF
        self._scene_preview_count = 0
        self._scene_preview_target = 10  # Number of ticks (~1 second at 90ms/tick)

        # Playhead tracking state
        self._last_blink_col = None
        self._clip_stop_blink_state = False
        self._last_loop_position_page = None
        self._blink_phase = 0
        
        # Boundary warning state
        self._boundary_warning_active = False
        self._boundary_direction = None  # 'up', 'down', 'left', 'right'
        self._boundary_blink_count = 0
        self._boundary_blink_max = 6  # 3 full on/off cycles
        self._boundary_blinking = False
        # Navigable boundary offsets (-1,0,+1) for top/left and bottom/right virtual bars
        self._x_boundary_offset = 0  # -1 = left virtual column, +1 = right virtual column
        self._y_boundary_offset = 0  # -1 = top virtual row, +1 = bottom virtual row
        
    # ==================== DRUM DETECTION ====================
    
    def _detect_drum_rack(self):
        """
        Detect if the current track has a drum rack and get loaded pads.
        
        Returns:
            list: List of MIDI note numbers for loaded drum pads, or default range
        """
        try:
            track = self._song.view.selected_track
            if not track or not hasattr(track, 'devices'):
                return self._row_note_offsets
            
            # Look for drum rack device
            for device in track.devices:
                if hasattr(device, 'can_have_drum_pads') and device.can_have_drum_pads:
                    # Found a drum rack
                    loaded_pads = []
                    if hasattr(device, 'drum_pads'):
                        for pad in device.drum_pads:
                            if pad and hasattr(pad, 'chains') and len(pad.chains) > 0:
                                # Pad is loaded
                                note = pad.note if hasattr(pad, 'note') else None
                                if note is not None:
                                    loaded_pads.append(note)
                    
                    if loaded_pads:
                        loaded_pads.sort(reverse=True)  # Reverse to match display order
                        self._log_info("Drum Rack: Found %d loaded pads (notes %d-%d)" % 
                                     (len(loaded_pads), loaded_pads[0], loaded_pads[-1]))
                        return loaded_pads
            
            # No drum rack found, use default range
            return self._row_note_offsets
            
        except Exception as e:
            self._log_error("_detect_drum_rack", e)
            return self._row_note_offsets
    
    # ==================== GRID RENDERING ====================
    
    def refresh_grid(self, matrix_rows):
        """
        Refresh the grid to show current drum notes.
        
        Args:
            matrix_rows: The matrix button rows
        """
        self._cs.log_message("refresh_grid: Starting")
        clip = self._get_cached_clip()
        if clip is None:
            self._cs.log_message("refresh_grid: No clip, clearing LEDs")
            self._clear_all_leds(matrix_rows)
            self._reset_grid_blink_states()
            return
        
        self._cs.log_message("refresh_grid: Got clip, rendering notes")

        try:
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
            note_len = self._note_lengths[self._note_length_index]
            page_start = self._time_page * self._steps_per_page * note_len
            page_length = self._steps_per_page * note_len

            self._clear_all_leds(matrix_rows)
            self._reset_grid_blink_states()

            self._page_notes_cache = {
                'page_start': page_start,
                'page_length': page_length,
                'rows': {}
            }

            # Determine dynamic right boundary col (used when x-boundary active on right)
            def _compute_right_red_col():
                last_valid = -1
                for c in range(self._steps_per_page):
                    if page_start + c * note_len < loop_length:
                        last_valid = c
                # Red column immediately after last valid, clamped to grid
                red_col = last_valid + 1
                if red_col < 0:
                    red_col = 0
                if red_col >= self._steps_per_page:
                    red_col = self._steps_per_page - 1
                return red_col

            x_off = getattr(self, '_x_boundary_offset', 0)
            y_off = getattr(self, '_y_boundary_offset', 0)

            rendered_cells = 0
            bottom_row_index = min(self._rows_visible - 1, len(matrix_rows) - 1)
            right_red_col = _compute_right_red_col()

            for row in range(self._rows_visible):
                # Skip drawing content in virtual boundary row
                if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_index):
                    # Boundary bar drawn later
                    continue

                # Map visible row to drum index
                visible_row = row - 1 if y_off == -1 else row
                row_offset = visible_row + self._drum_row_base
                if row_offset < 0 or row_offset >= len(self._row_note_offsets):
                    continue

                pitch = self._row_note_offsets[row_offset]
                row_is_selected = (row_offset == self._selected_drum)
                notes_for_row = self._collect_notes_for_row(clip, pitch, page_start, page_length)
                self._page_notes_cache['rows'][visible_row] = notes_for_row

                for col in range(self._steps_per_page):
                    # Skip drawing content in virtual boundary column
                    if x_off == -1 and col == 0:
                        continue
                    if x_off == 1:
                        if col == right_red_col:
                            continue
                        if col > right_red_col:
                            continue

                    effective_col = col - (1 if x_off == -1 else 0)
                    column_start = page_start + effective_col * note_len
                    if column_start < 0 or column_start >= loop_length:
                        continue

                    color, pattern, subdivision = self._compute_cell_visual(notes_for_row, column_start, note_len, row_is_selected)

                    if pattern:
                        self._set_pad_led_color(col, row, pattern[0], matrix_rows)
                        self._register_grid_blink(row, col, pattern, subdivision)
                        rendered_cells += 1
                    else:
                        self._set_pad_led_color(col, row, color, matrix_rows)
                        self._register_grid_blink(row, col, None, 0)
                        if color != self._LED_OFF:
                            rendered_cells += 1

            self._log_debug("refresh_grid: rendered %d active cells" % rendered_cells)

        except Exception as e:
            self._log_error("refresh_grid", e)
            # If refresh fails, make sure any stale playhead column is cleared safely
            self._clear_playhead_column(matrix_rows)

        # Reapply playhead highlight after redraw so it doesn't disappear until next tick
        try:
            self.update_playhead_leds(matrix_rows, None)
        except Exception as exc:
            self._log_error("refresh_grid(update_playhead)", exc)
        
        # Draw persistent boundary bars on the grid edges (based on boundary offsets)
        try:
            self._draw_static_boundaries(matrix_rows)
        except Exception as exc:
            self._log_error("refresh_grid(draw_static_boundaries)", exc)

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

    def _draw_boundary_warning(self, matrix_rows):
        """
        Draw RED boundary warning on the 8x5 grid edges when navigation is blocked.
        - UP boundary: RED on top row (row 0)
        - DOWN boundary: RED on bottom row (row 4)
        - LEFT boundary: RED on left column (col 0)
        - RIGHT boundary: RED on rightmost visible column (col 7 or last within loop)
        Blinks only after repeated attempts; first attempt shows solid RED.
        """
        if not matrix_rows or not self._boundary_warning_active:
            return
        try:
            # Determine color based on blink state
            blink_on = True
            if self._boundary_blinking:
                self._boundary_blink_count = (self._boundary_blink_count + 1) % 12  # slow blink
                blink_on = (self._boundary_blink_count // 3) % 2 == 0
            color = self._LED_RED if blink_on else self._LED_OFF

            if self._boundary_direction == 'up':
                # Top row RED
                for col in range(min(self._steps_per_page, len(matrix_rows[0]))):
                    self._set_pad_led_color(col, 0, color, matrix_rows)
            elif self._boundary_direction == 'down':
                # Bottom row RED
                bottom_row = min(self._rows_visible - 1, len(matrix_rows) - 1)
                for col in range(min(self._steps_per_page, len(matrix_rows[bottom_row]))):
                    self._set_pad_led_color(col, bottom_row, color, matrix_rows)
            elif self._boundary_direction == 'left':
                # Left column RED
                for row in range(min(self._rows_visible, len(matrix_rows))):
                    self._set_pad_led_color(0, row, color, matrix_rows)
            elif self._boundary_direction == 'right':
                # Rightmost visible column RED
                loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
                note_len = self._note_lengths[self._note_length_index]
                page_start = self._time_page * self._steps_per_page * note_len
                rightmost_col = -1
                for col in range(self._steps_per_page):
                    column_start = page_start + col * note_len
                    if column_start < loop_length:
                        rightmost_col = col
                if rightmost_col >= 0:
                    for row in range(min(self._rows_visible, len(matrix_rows))):
                        self._set_pad_led_color(rightmost_col, row, color, matrix_rows)
        except Exception as e:
            self._log_error("_draw_boundary_warning", e)
    
    def _draw_static_boundaries(self, matrix_rows):
        """
        Always draw static RED bars on edges when at boundaries.
        These persist while at the boundary, and do not blink unless
        a repeated navigation attempt occurs (handled by _draw_boundary_warning).
        """
        if not matrix_rows:
            return
        
        try:
            # Compute time info
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
            note_len = self._note_lengths[self._note_length_index]
            page_start = self._time_page * self._steps_per_page * note_len

            x_off = getattr(self, '_x_boundary_offset', 0)
            y_off = getattr(self, '_y_boundary_offset', 0)

            # Draw top row if in top virtual boundary
            if y_off == -1 and not (self._boundary_warning_active and self._boundary_blinking and self._boundary_direction == 'up'):
                for col in range(min(self._steps_per_page, len(matrix_rows[0]))):
                    self._set_pad_led_color(col, 0, self._LED_RED, matrix_rows)
            
            # Draw bottom row if in bottom virtual boundary
            if y_off == 1 and len(matrix_rows) > 0 and not (self._boundary_warning_active and self._boundary_blinking and self._boundary_direction == 'down'):
                bottom_row = min(self._rows_visible - 1, len(matrix_rows) - 1)
                for col in range(min(self._steps_per_page, len(matrix_rows[bottom_row]))):
                    self._set_pad_led_color(col, bottom_row, self._LED_RED, matrix_rows)
            
            # Draw left column if in left virtual boundary
            if x_off == -1 and not (self._boundary_warning_active and self._boundary_blinking and self._boundary_direction == 'left'):
                for row in range(min(self._rows_visible, len(matrix_rows))):
                    self._set_pad_led_color(0, row, self._LED_RED, matrix_rows)
            
            # Draw right boundary column if in right virtual boundary
            if x_off == 1 and not (self._boundary_warning_active and self._boundary_blinking and self._boundary_direction == 'right'):
                # Determine column immediately after last valid step
                last_valid = -1
                for c in range(self._steps_per_page):
                    if page_start + c * note_len < loop_length:
                        last_valid = c
                red_col = last_valid + 1
                if red_col < 0:
                    red_col = 0
                if red_col >= self._steps_per_page:
                    red_col = self._steps_per_page - 1
                for row in range(min(self._rows_visible, len(matrix_rows))):
                    self._set_pad_led_color(red_col, row, self._LED_RED, matrix_rows)
        except Exception as e:
            self._log_error("_draw_static_boundaries", e)
    
    
    def _clear_boundary_leds(self, matrix_rows=None):
        """Grid will be redrawn by refresh; nothing extra to clear for on-grid boundaries."""
        return
    
    def trigger_boundary_warning(self, direction):
        """Trigger boundary overlay; repeated trigger starts blinking."""
        if self._boundary_warning_active and self._boundary_direction == direction:
            # Second (or further) attempt in same direction -> start blinking
            self._boundary_blinking = True
            # keep blink counter running
        else:
            # First attempt -> show solid
            self._boundary_warning_active = True
            self._boundary_direction = direction
            self._boundary_blinking = False
            self._boundary_blink_count = 0
        try:
            self._log_info("Boundary warning: %s (blinking=%s)" % (direction, str(self._boundary_blinking)))
        except Exception:
            pass

    def _collect_notes_for_row(self, clip, pitch, start_time, window_length):
        """Collect notes for a given pitch within the visible window."""
        notes = []
        epsilon = 0.001
        fetch_start = max(0.0, float(start_time) - epsilon)
        fetch_length = float(window_length) + (epsilon * 2.0)
        try:
            if hasattr(clip, 'get_notes_extended'):
                raw = clip.get_notes_extended(int(pitch), 1, fetch_start, fetch_length)
            else:
                raw = clip.get_notes(fetch_start, int(pitch), fetch_length, 1)

            for note in raw or []:
                if hasattr(note, 'start_time'):
                    start = float(note.start_time)
                    duration_value = getattr(note, 'duration', 0.0)
                    velocity_value = getattr(note, 'velocity', None)
                else:
                    start = float(note[1])
                    duration_value = note[2] if len(note) > 2 else 0.0
                    velocity_value = note[3] if len(note) > 3 else None

                duration = max(0.0001, float(duration_value))
                velocity = int(velocity_value) if velocity_value is not None else 100

                notes.append({
                    'start': start,
                    'duration': duration,
                    'velocity': velocity
                })

        except Exception as e:
            self._log_error("_collect_notes_for_row", e)

        return notes

    def _clear_playhead_column(self, matrix_rows):
        """Restore LEDs for the last highlighted playhead column."""
        if self._last_blink_col is None or not matrix_rows:
            return

        try:
            for row in range(min(self._rows_visible, len(matrix_rows))):
                self._redraw_cell(self._last_blink_col, row, matrix_rows)
        except Exception as exc:
            self._log_error("_clear_playhead_column", exc)
        finally:
            self._last_blink_col = None

    def _has_note_overlap_at(self, clip, pitch, start, step_duration):
        """Detect if a note overlaps a step within a tempo-aware epsilon."""
        if clip is None:
            return False

        try:
            step_duration = float(step_duration)
            epsilon = max(0.001, min(0.02, 0.2 * step_duration))
            loop_start = float(getattr(clip, 'loop_start', 0.0))
            from_time = max(0.0, loop_start + float(start) - epsilon)
            time_span = max(2.0 * epsilon, 0.004)

            if hasattr(clip, 'get_notes_extended'):
                existing = clip.get_notes_extended(int(pitch), 1, from_time, time_span)
            else:
                existing = clip.get_notes(from_time, int(pitch), time_span, 1)
            return bool(existing)
        except Exception as exc:
            self._log_error("_has_note_overlap_at", exc)
            return False

    def _has_overlap_in_list(self, notes, start, duration):
        if not notes:
            return False
        EPSILON = 1e-5
        end = start + float(duration)
        for n in notes:
            ns = float(n['start'])
            ne = ns + float(n['duration'])
            if ns < end - EPSILON and ne > start + EPSILON:
                return True
        return False

    def _redraw_cell(self, col, row, matrix_rows):
        """Recompute and light a cell based on its note state."""
        if not matrix_rows or not (0 <= row < len(matrix_rows)):
            return

        pitch_index = row + self._drum_row_base
        if pitch_index >= len(self._row_note_offsets):
            return

        pitch = self._row_note_offsets[pitch_index]
        step = col + self._time_page * self._steps_per_page
        note_len = self._note_lengths[self._note_length_index]
        start = step * note_len

        clip = self._get_cached_clip()
        if clip is None:
            return

        try:
            clip_loop_len = float(getattr(clip, 'loop_end', 0.0) - getattr(clip, 'loop_start', 0.0))
            if clip_loop_len <= 0.0:
                clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
        except Exception:
            clip_loop_len = float(self._loop_bars_options[self._loop_bars_index] * 4.0)

        if start >= clip_loop_len:
            return

        has_note = self._has_note_overlap_at(clip, pitch, start, note_len)

        if pitch_index == self._selected_drum:
            color = self._LED_GREEN if has_note else self._LED_BLUE
        else:
            color = self._LED_GREEN if has_note else self._LED_OFF

        self._set_pad_led_color(col, row, color, matrix_rows)

    def update_playhead_leds(self, matrix_rows, clip_stop_buttons=None):
        """Advance the playhead highlight on the grid and clip-stop row."""
        if not matrix_rows or self._song is None:
            self._log_info("update_playhead_leds: No matrix rows or song")
            return
            
        # Add time import if not already present
        try:
            import time
        except ImportError:
            pass
            
        # Debug: Log when playhead updates are called
        if not hasattr(self, '_last_playhead_log') or (time.time() - getattr(self, '_last_playhead_log', 0)) > 1.0:
            self._log_info(f"update_playhead_leds: Updating playhead (matrix_rows: {len(matrix_rows)} rows)")
            self._last_playhead_log = time.time()

        try:
            note_len = float(self._note_lengths[self._note_length_index])
            if note_len <= 0.0:
                self._log_info("update_playhead_leds: Invalid note length")
                return

            clip = self._get_cached_clip()
            if clip is None:
                self._log_info("update_playhead_leds: No clip available")
                return

            # Log clip properties for debugging
            self._log_info(f"Clip: loop_start={getattr(clip, 'loop_start', 'N/A')}, loop_end={getattr(clip, 'loop_end', 'N/A')}, "
                          f"playing_position={getattr(clip, 'playing_position', 'N/A')}, "
                          f"length={getattr(clip, 'length', 'N/A')}")

            loop_length = float(self._loop_bars_options[self._loop_bars_index] * 4.0)
            if hasattr(clip, 'loop_end') and hasattr(clip, 'loop_start'):
                clip_len = float(clip.loop_end) - float(clip.loop_start)
                if clip_len > 0.0:
                    loop_length = clip_len
                    self._log_info(f"Using clip loop length: {loop_length}")

            loop_length = max(loop_length, note_len)
            self._log_info(f"Final loop_length: {loop_length}, note_len: {note_len}")

            song_time = float(getattr(self._song, 'current_song_time', 0.0))
            pos = 0.0
            method = "song_time (fallback)"

            # Try to get position using the best available method
            if hasattr(clip, 'playing_position'):
                try:
                    pos = float(clip.playing_position)
                    method = "clip.playing_position"
                    self._log_info(f"Using clip.playing_position: {pos}")
                except Exception as e:
                    self._log_error("Error getting playing_position", e)
                    method = "clip.playing_position failed"
            
            if method == "clip.playing_position failed" and hasattr(clip, 'loop_start'):
                try:
                    clip_start = float(clip.loop_start)
                    pos = (song_time - clip_start) % loop_length
                    method = "song_time - loop_start"
                    self._log_info(f"Using song_time - loop_start: {pos} (song_time: {song_time}, clip_start: {clip_start})")
                except Exception as e:
                    self._log_error("Error calculating pos from loop_start", e)
                    method = "song_time - loop_start failed"
            
            if method.endswith("failed"):
                pos = song_time % loop_length
                method = "song_time % loop_length"
                self._log_info(f"Falling back to song_time % loop_length: {pos}")

            self._log_info(f"Final position: {pos} (method: {method})")

            # Use floor to derive step index to avoid boundary oscillation at very small lengths
            step_idx = int(pos / note_len)
            col_base = step_idx % self._steps_per_page
            
            # Check if we're beyond the actual loop length
            if pos >= loop_length:
                # Don't show playhead beyond loop end
                self._clear_playhead_column(matrix_rows)
                self._last_blink_col = None
                return

            # Honor virtual boundary columns
            x_off = getattr(self, '_x_boundary_offset', 0)
            y_off = getattr(self, '_y_boundary_offset', 0)

            # Compute right boundary red column when in right boundary layer
            loop_length = float(loop_length)
            page_start = self._time_page * self._steps_per_page * note_len
            last_valid = -1
            for c in range(self._steps_per_page):
                if page_start + c * note_len < loop_length:
                    last_valid = c
            right_red_col = max(0, min(self._steps_per_page - 1, last_valid + 1))

            if x_off == -1:
                col_vis = min(self._steps_per_page - 1, col_base + 1)
                col_eff = max(0, col_vis - 1)
            elif x_off == 1:
                col_vis = min(col_base, right_red_col - 1) if right_red_col > 0 else 0
                col_eff = col_vis
            else:
                col_vis = col_base
                col_eff = col_base

            # Compute total steps for loop
            total_steps = int(loop_length / note_len) if note_len > 0 else 0

            # Clear previous trail columns (redraw their content) so we don't leave artifacts
            try:
                prev_trails = getattr(self, '_last_trail_cols', []) or []
                if prev_trails:
                    for prev_col in set(prev_trails):
                        # Redraw previous trail column back to content (skip boundary bars)
                        for row in range(min(self._rows_visible, len(matrix_rows))):
                            bottom_row_idx = min(self._rows_visible - 1, len(matrix_rows) - 1)
                            if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_idx):
                                continue
                            # Skip boundary columns
                            if (x_off == -1 and prev_col == 0) or (x_off == 1 and prev_col >= right_red_col):
                                continue
                            eff_row = row - 1 if y_off == -1 else row
                            eff_col = prev_col - 1 if x_off == -1 else prev_col
                            if eff_row < 0 or eff_col < 0:
                                continue
                            pitch_index = eff_row + self._drum_row_base
                            if pitch_index < 0 or pitch_index >= len(self._row_note_offsets):
                                continue
                            pitch = self._row_note_offsets[pitch_index]
                            page_len = self._steps_per_page * note_len
                            notes_for_row = self._collect_notes_for_row(clip, pitch, page_start, page_len)
                            step_start = page_start + eff_col * note_len
                            if step_start >= loop_length:
                                continue
                            color, pattern, subdivision = self._compute_cell_visual(notes_for_row, step_start, note_len, (pitch_index == self._selected_drum))
                            if pattern:
                                self._set_pad_led_color(prev_col, row, pattern[0], matrix_rows)
                            else:
                                self._set_pad_led_color(prev_col, row, color, matrix_rows)
            except Exception as trail_clear_exc:
                self._log_error("update_playhead_leds(clear_trails)", trail_clear_exc)

            # Build and render dim trail so every skipped column is visible at micro lengths
            try:
                last_step = getattr(self, '_last_step_idx', None)
                progressed = 0
                if last_step is not None and total_steps > 0:
                    progressed = (step_idx - last_step) % total_steps
                micro = (note_len <= 0.125)
                trail_map = getattr(self, '_playhead_trail_map', {}) if micro else {}
                # Adaptive trail TTL based on tempo and step duration so skipped columns remain visible
                try:
                    tempo = float(getattr(self._song, 'tempo', 120.0))
                except Exception:
                    tempo = 120.0
                beat_sec = 60.0 / max(1.0, tempo)
                step_sec = max(0.001, beat_sec * note_len)
                tick_sec = 0.03  # schedule_message tick ~30ms
                trail_ttl = int(round(tick_sec / step_sec))
                if trail_ttl < 1:
                    trail_ttl = 1
                if trail_ttl > 3:
                    trail_ttl = 3
                
                # Initialize counter before using it
                try:
                    ctr = getattr(self, '_clip_stop_tick_ctr', 0) + 1
                except Exception:
                    ctr = 1
                
                # Always update clip stop buttons to show current page
                if clip_stop_buttons:
                    loop_pages = max(1, (total_steps + self._steps_per_page - 1) // self._steps_per_page)
                    current_page = step_idx // self._steps_per_page
                    
                    # Log clip stop button state for debugging
                    self._log_info(f"Clip stop buttons - current_page: {current_page}, loop_pages: {loop_pages}, step_idx: {step_idx}, total_steps: {total_steps}")
                    
                    # Update clip stop buttons for all note lengths
                    for idx, btn in enumerate(clip_stop_buttons):
                        if not btn or not hasattr(btn, 'send_value'):
                            continue
                        try:
                            if idx == current_page:
                                color = self._LED_PINK if idx == self._time_page else self._LED_RED
                                btn.send_value(color if self._clip_stop_blink_state else self._LED_OFF, True)
                            elif idx < loop_pages:
                                btn.send_value(self._LED_ORANGE, True)
                            else:
                                btn.send_value(self._LED_OFF, True)
                        except Exception as btn_exc:
                            self._log_error("update_playhead_leds(clip_stop)", btn_exc)

                # Toggle blink state and update counters
                self._clip_stop_blink_state = not self._clip_stop_blink_state
                self._last_loop_position_page = step_idx // self._steps_per_page
                self._clip_stop_tick_ctr = ctr
                # Add intermediate columns with a short TTL
                for i in range(1, progressed):
                    step_i = (last_step + i) % total_steps
                    step_page = step_i // self._steps_per_page
                    if step_page != self._time_page:
                        continue
                    col_base_i = step_i % self._steps_per_page
                    if x_off == -1:
                        col_vis_i = min(self._steps_per_page - 1, col_base_i + 1)
                        col_eff_i = max(0, col_vis_i - 1)
                    elif x_off == 1:
                        col_vis_i = min(col_base_i, right_red_col - 1) if right_red_col > 0 else 0
                        col_eff_i = col_vis_i
                    else:
                        col_vis_i = col_base_i
                        col_eff_i = col_base_i
                        trail_map[col_vis_i] = trail_ttl  # hold adaptively (bright trail)

                # Render and age trail columns
                if micro and trail_map:
                    rows_count = min(self._rows_visible, len(matrix_rows))
                    clip_for_check = clip if clip is not None else self._get_cached_clip()
                    expired = []
                    for tcol, ttl in list(trail_map.items()):
                        # Skip boundary cols
                        if (x_off == -1 and tcol == 0) or (x_off == 1 and tcol >= right_red_col):
                            expired.append(tcol)
                            continue
                        for row in range(rows_count):
                            bottom_row_idx = min(self._rows_visible - 1, len(matrix_rows) - 1)
                            if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_idx):
                                continue
                            eff_row = row - 1 if y_off == -1 else row
                            if eff_row < 0:
                                continue
                            pitch_index = eff_row + self._drum_row_base
                            if pitch_index >= len(self._row_note_offsets):
                                continue
                            step_start_i = (self._time_page * self._steps_per_page + (tcol - 1 if x_off == -1 else tcol)) * note_len
                            if clip_for_check is not None and step_start_i < loop_length:
                                pitch = self._row_note_offsets[pitch_index]
                                cache = getattr(self, '_page_notes_cache', None)
                                if cache and cache.get('page_start') == page_start and cache.get('page_length') == page_len:
                                    notes_for_row = cache.get('rows', {}).get(eff_row)
                                    has_note_i = self._has_overlap_in_list(notes_for_row, step_start_i, note_len)
                                else:
                                    has_note_i = self._has_note_overlap_at(clip_for_check, pitch, step_start_i, note_len)
                                # Bright trail so each skipped column is clearly visible
                                color_i = self._LED_YELLOW if has_note_i else self._LED_TEAL
                                try:
                                    if 0 <= row < len(matrix_rows) and 0 <= tcol < len(matrix_rows[row]):
                                        btn = matrix_rows[row][tcol]
                                        if btn and hasattr(btn, 'send_value'):
                                            btn.send_value(color_i, True)
                                except Exception:
                                    self._set_pad_led_color(tcol, row, color_i, matrix_rows)
                        # Decrement TTL
                        ttl -= 1
                        if ttl <= 0:
                            expired.append(tcol)
                        else:
                            trail_map[tcol] = ttl

                    # Redraw expired columns back to content
                    if expired:
                        for prev_col in expired:
                            for row in range(min(self._rows_visible, len(matrix_rows))):
                                bottom_row_idx = min(self._rows_visible - 1, len(matrix_rows) - 1)
                                if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_idx):
                                    continue
                                if (x_off == -1 and prev_col == 0) or (x_off == 1 and prev_col >= right_red_col):
                                    continue
                                eff_row = row - 1 if y_off == -1 else row
                                eff_col = prev_col - 1 if x_off == -1 else prev_col
                                if eff_row < 0 or eff_col < 0:
                                    continue
                                pitch_index = eff_row + self._drum_row_base
                                if pitch_index < 0 or pitch_index >= len(self._row_note_offsets):
                                    continue
                                pitch = self._row_note_offsets[pitch_index]
                                page_len = self._steps_per_page * note_len
                                notes_for_row = None
                                cache = getattr(self, '_page_notes_cache', None)
                                if cache and cache.get('page_start') == page_start and cache.get('page_length') == page_len:
                                    notes_for_row = cache.get('rows', {}).get(eff_row)
                                if notes_for_row is None:
                                    notes_for_row = self._collect_notes_for_row(clip, pitch, page_start, page_len)
                                step_start = page_start + eff_col * note_len
                                if step_start >= loop_length:
                                    continue
                                color, pattern, subdivision = self._compute_cell_visual(notes_for_row, step_start, note_len, (pitch_index == self._selected_drum))
                                if pattern:
                                    self._set_pad_led_color(prev_col, row, pattern[0], matrix_rows)
                                else:
                                    self._set_pad_led_color(prev_col, row, color, matrix_rows)
                            try:
                                trail_map.pop(prev_col, None)
                            except Exception:
                                pass

                # Store updated trail map
                if micro:
                    self._playhead_trail_map = trail_map
            except Exception as trail_exc:
                self._log_error("update_playhead_leds(trail)", trail_exc)

            # Current playhead column to display (always the actual current column)
            disp_col_vis, disp_col_eff = col_vis, col_eff

            # Always render the current playhead column in RED
            for row in range(min(self._rows_visible, len(matrix_rows))):
                # Skip boundary rows
                bottom_row_idx = min(self._rows_visible - 1, len(matrix_rows) - 1)
                if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_idx):
                    continue
                
                # Skip boundary columns
                if (x_off == -1 and disp_col_vis == 0) or (x_off == 1 and disp_col_vis >= right_red_col):
                    continue
                
                # Set playhead column to RED
                self._set_pad_led_color(disp_col_vis, row, self._LED_RED, matrix_rows)
                self._log_info(f"Set playhead LED at col={disp_col_vis}, row={row}")

            if disp_col_vis != self._last_blink_col:
                if self._last_blink_col is not None:
                    prev_col = self._last_blink_col
                    # Redraw previous playhead column back to content (skip boundary bars)
                    for row in range(min(self._rows_visible, len(matrix_rows))):
                        # Skip boundary rows
                        bottom_row_idx = min(self._rows_visible - 1, len(matrix_rows) - 1)
                        if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_idx):
                            continue

                        # Skip boundary columns
                        if (x_off == -1 and prev_col == 0) or (x_off == 1 and prev_col >= right_red_col):
                            continue

                        # Map visible to effective indices
                        eff_row = row - 1 if y_off == -1 else row
                        eff_col = prev_col - 1 if x_off == -1 else prev_col
                        if eff_row < 0 or eff_col < 0:
                            continue

                        # Recompute content color for this cell
                        pitch_index = eff_row + self._drum_row_base
                        if pitch_index < 0 or pitch_index >= len(self._row_note_offsets):
                            continue
                        pitch = self._row_note_offsets[pitch_index]
                        page_len = self._steps_per_page * note_len
                        notes_for_row = None
                        cache = getattr(self, '_page_notes_cache', None)
                        if cache and cache.get('page_start') == page_start and cache.get('page_length') == page_len:
                            notes_for_row = cache.get('rows', {}).get(eff_row)
                        if notes_for_row is None:
                            notes_for_row = self._collect_notes_for_row(clip, pitch, page_start, page_len)
                        step_start = page_start + eff_col * note_len
                        if step_start >= loop_length:
                            continue
                        color, pattern, subdivision = self._compute_cell_visual(notes_for_row, step_start, note_len, (pitch_index == self._selected_drum))
                        if pattern:
                            self._set_pad_led_color(prev_col, row, pattern[0], matrix_rows)
                        else:
                            self._set_pad_led_color(prev_col, row, color, matrix_rows)

                self._blink_phase = 0
                self._last_blink_col = disp_col_vis
            if step_idx % 8 == 0:
                try:
                    self._cs.log_message("Playhead [%s]: pos=%.3f song_time=%.3f step=%d col=%d page=%d note_len=%.3f" % (
                        method,
                        pos,
                        song_time,
                        step_idx,
                        col_base,
                        step_idx // self._steps_per_page,
                        note_len
                    ))
                except Exception:
                    pass

        except Exception as exc:
            self._log_error("update_playhead_leds", exc)
            self._clear_playhead_column(matrix_rows)

    def _compute_cell_visual(self, notes, column_start, column_length, row_selected):
        """Determine color and blink pattern for a grid cell."""
        EPSILON = 1e-5
        column_end = column_start + column_length

        notes_in_cell = [note for note in notes
                          if note['start'] < column_end - EPSILON
                          and (note['start'] + note['duration']) > column_start + EPSILON]

        if not notes_in_cell:
            base_color = self._LED_BLUE if row_selected else self._LED_OFF
            return base_color, None, 0.0

        def _solid_cell_color():
            mid_time = column_start + (column_length * 0.5)
            mid_note = self._find_note_covering(notes_in_cell, mid_time)
            if mid_note:
                return self.get_color_for_duration(mid_note['duration'])
            # Fallback: use the longest note in the cell as representative
            rep_note = max(notes_in_cell, key=lambda n: n['duration'])
            return self.get_color_for_duration(rep_note['duration'])

        # If any note covers the entire cell (>= cell length), render solid color (no blink)
        for note in notes_in_cell:
            note_start = note['start']
            note_end = note_start + note['duration']
            if (note_start <= column_start + EPSILON and note_end >= column_end - EPSILON) or (note['duration'] >= column_length - EPSILON):
                color = _solid_cell_color()
                return color, None, 0.0

        # Compute if sub-note blinking should occur: only if min note duration < cell length
        min_dur = min(max(note['duration'], EPSILON) for note in notes_in_cell)
        if not (min_dur < column_length - EPSILON):
            # No note smaller than cell: solid color
            color = _solid_cell_color()
            return color, None, 0.0

        base_duration = max(EPSILON, min(min_dur, column_length))
        subdivisions = int(round(column_length / base_duration))
        subdivisions = max(2, min(16, subdivisions))

        if subdivisions <= 1:
            color = _solid_cell_color()
            return color, None, 0.0

        base_duration = column_length / float(subdivisions)
        pattern = []
        use_full = True
        base_color = _solid_cell_color()
        dim_color = self.get_dim_color(base_color)

        # Blink entire cell uniformly (full/dim), independent of exact note coverage,
        # since we only blink to indicate presence of faster notes than the grid cell.
        for idx in range(subdivisions):
            color_value = base_color if use_full else dim_color
            use_full = not use_full
            pattern.append(color_value)

        return pattern[0], pattern, base_duration

    def _find_note_covering(self, notes, time_point):
        """Return the first note covering the supplied time."""
        EPSILON = 1e-5
        for note in notes:
            start = note['start'] - EPSILON
            end = note['start'] + note['duration'] + EPSILON
            if start <= time_point < end:
                return note
        return None

    
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
            # Respect virtual boundary layers: ignore presses on boundary bars
            note_len = self._note_lengths[self._note_length_index]
            page_start = self._time_page * self._steps_per_page * note_len
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0

            x_off = getattr(self, '_x_boundary_offset', 0)
            y_off = getattr(self, '_y_boundary_offset', 0)

            # Compute right boundary red column when in right boundary layer
            right_red_col = None
            if x_off == 1:
                last_valid = -1
                for c in range(self._steps_per_page):
                    if page_start + c * note_len < loop_length:
                        last_valid = c
                right_red_col = max(0, min(self._steps_per_page - 1, last_valid + 1))

            bottom_row_index = min(self._rows_visible - 1, len(matrix_rows) - 1) if matrix_rows else (self._rows_visible - 1)

            # Non-selectable boundary cells
            if (y_off == -1 and row == 0) or (y_off == 1 and row == bottom_row_index):
                return False
            if (x_off == -1 and col == 0):
                return False
            if (x_off == 1 and right_red_col is not None and col >= right_red_col):
                return False

            # Map visible to effective indices inside content
            effective_row = row - 1 if y_off == -1 else row
            effective_col = col - 1 if x_off == -1 else col
            if effective_row < 0 or effective_col < 0:
                return False

            # Calculate pitch and timing
            row_offset = effective_row + self._drum_row_base
            if row_offset < 0 or row_offset >= len(self._row_note_offsets):
                return False
            
            pitch = self._row_note_offsets[row_offset]
            step = effective_col + self._time_page * self._steps_per_page
            start = step * note_len
            
            # Get clip
            clip = self._ensure_clip()
            if clip is None:
                return False
            
            # Check loop bounds
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
                
                self._log_debug("Removed note: pitch=%d time=%.3f" % (pitch, start))
                
                # Update LED
                color = self._LED_BLUE if row_offset == self._selected_drum else self._LED_OFF
                self._set_pad_led_color(col, row, color, matrix_rows)
                
            else:
                # Add note
                velocity = self._drum_velocity[row_offset]
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
                
                self._log_debug("Added note: pitch=%d time=%.3f vel=%d" % (pitch, start, velocity))
                
                # Update LED
                self._set_pad_led_color(col, row, self._LED_GREEN, matrix_rows)
            
            return True
            
        except Exception as e:
            self._log_error("toggle_note", e)
            return False
    
    # ==================== FUNCTION SYSTEM ====================
    
    def cycle_function(self):
        """
        Cycle to the next function in the sequence.
        
        Returns:
            int: New function ID
        """
        functions = [
            self._FUNCTION_NONE,
            self._FUNCTION_CLEAR,
            self._FUNCTION_COPY,
            self._FUNCTION_PASTE,
            self._FUNCTION_MPE,
            self._FUNCTION_FILL_QUARTER,
            self._FUNCTION_FILL_EIGHTH,
            self._FUNCTION_FILL_SIXTEENTH,
            self._FUNCTION_FILL_WHOLE,
            self._FUNCTION_QUANT_TRIPLET,
            self._FUNCTION_QUANT_SEPTUPLET
        ]
        
        try:
            current_index = functions.index(self._current_function)
            next_index = (current_index + 1) % len(functions)
            self._current_function = functions[next_index]
            
            func_name = self._function_names.get(self._current_function, "UNKNOWN")
            self._log_info("Function cycled to: %s" % func_name)
            
            return self._current_function
            
        except Exception as e:
            self._log_error("cycle_function", e)
            return self._current_function
    
    def _visible_to_absolute_drum(self, visible_index):
        """Convert a visible row index (0-7) to an absolute drum index."""
        absolute = self._drum_row_base + visible_index
        if absolute < 0 or absolute >= len(self._row_note_offsets):
            return None
        return absolute

    def toggle_drum_function(self, drum_index):
        """
        Cycle the function assignment for a drum.
        
        Args:
            drum_index: Index of the drum (0-15)
        """
        try:
            absolute_index = self._visible_to_absolute_drum(drum_index)
            if absolute_index is None or absolute_index >= len(self._drum_functions):
                return
            
            # Get current function for this drum
            current = self._drum_functions[absolute_index]
            
            # Function cycle order
            functions = [
                self._FUNCTION_NONE,
                self._FUNCTION_CLEAR,
                self._FUNCTION_COPY,
                self._FUNCTION_PASTE,
                self._FUNCTION_MPE,
                self._FUNCTION_FILL_QUARTER,
                self._FUNCTION_FILL_EIGHTH,
                self._FUNCTION_FILL_SIXTEENTH,
                self._FUNCTION_FILL_WHOLE,
                self._FUNCTION_QUANT_TRIPLET,
                self._FUNCTION_QUANT_SEPTUPLET
            ]
            
            # Find current index and cycle to next
            try:
                current_index = functions.index(current)
            except ValueError:
                current_index = 0
            
            next_index = (current_index + 1) % len(functions)
            new_function = functions[next_index]
            
            # Update drum function
            self._drum_functions[absolute_index] = new_function
            
            # Log the change
            func_name = self._function_names.get(new_function, "UNKNOWN")
            self._log_info("Drum %d function changed: %d -> %d (%s)" % (absolute_index, current, new_function, func_name))
            self._cs.log_message("Drum %d function cycled to: %s (func=%d)" % (absolute_index, func_name, new_function))

        except Exception as e:
            self._log_error("toggle_drum_function", e)
    
    def execute_function(self):
        """
        Execute the currently selected function on all assigned drums.
        
        Returns:
            int: Number of drums operated on
        """
        try:
            # Find all drums with current function assigned
            target_drums = []
            for i, func in enumerate(self._drum_functions):
                if func == self._current_function and func != self._FUNCTION_NONE:
                    target_drums.append(i)
            
            if not target_drums:
                self._log_info("No drums assigned to current function")
                return 0
            
            func_name = self._function_names.get(self._current_function, "UNKNOWN")
            self._log_info("Executing %s on %d drums" % (func_name, len(target_drums)))
            
            # Execute function on each drum
            for drum_idx in target_drums:
                if self._current_function == self._FUNCTION_CLEAR:
                    self._clear_drum_notes(drum_idx)
                elif self._current_function == self._FUNCTION_COPY:
                    self._copy_drum_notes(drum_idx)
                elif self._current_function == self._FUNCTION_PASTE:
                    self._paste_drum_notes(drum_idx)
                elif self._current_function == self._FUNCTION_FILL_QUARTER:
                    self._fill_drum_notes(drum_idx, 1.0)
                elif self._current_function == self._FUNCTION_FILL_EIGHTH:
                    self._fill_drum_notes(drum_idx, 0.5)
                elif self._current_function == self._FUNCTION_FILL_SIXTEENTH:
                    self._fill_drum_notes(drum_idx, 0.25)
                elif self._current_function == self._FUNCTION_FILL_WHOLE:
                    self._fill_drum_notes(drum_idx, 4.0)
                elif self._current_function == self._FUNCTION_QUANT_TRIPLET:
                    self._quantize_drum_notes(drum_idx, 3)
                elif self._current_function == self._FUNCTION_QUANT_SEPTUPLET:
                    self._quantize_drum_notes(drum_idx, 7)
            
            # Clear assignments after execution
            for drum_idx in target_drums:
                self._drum_functions[drum_idx] = self._FUNCTION_NONE
            
            return len(target_drums)
            
        except Exception as e:
            self._log_error("execute_function", e)
            return 0

    def _quantize_drum_notes(self, drum_index, division):
        """Quantize notes on a drum to triplets/septuplets."""
        try:
            if drum_index < 0 or drum_index >= len(self._row_note_offsets):
                return

            pitch = self._row_note_offsets[drum_index]
            clip = self._ensure_clip()
            if clip is None:
                return

            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(pitch, 1, 0.0, clip.length)
            else:
                notes = clip.get_notes(0.0, pitch, clip.length, 1)

            if not notes:
                self._cs.log_message("QUANT: Drum %d has no notes" % drum_index)
                return

            note_len = self._note_lengths[self._note_length_index]
            base_step = note_len / division

            new_notes = []
            for note in notes:
                if hasattr(note, 'start_time'):
                    start = float(note.start_time)
                    duration = float(getattr(note, 'duration', 0.0))
                    velocity = int(getattr(note, 'velocity', 100))
                    mute = bool(getattr(note, 'mute', False))
                else:
                    start = float(note[1])
                    duration = float(note[2])
                    velocity = int(note[3]) if len(note) > 3 else 100
                    mute = bool(note[4]) if len(note) > 4 else False

                quantized_start = round(start / base_step) * base_step
                quantized_duration = round(duration / base_step) * base_step
                quantized_duration = max(base_step, quantized_duration)

                note_spec = Live.Clip.MidiNoteSpecification(
                    pitch=int(pitch),
                    start_time=float(quantized_start),
                    duration=float(quantized_duration),
                    velocity=int(velocity),
                    mute=bool(mute)
                )
                new_notes.append(note_spec)

            if hasattr(clip, 'remove_notes_extended'):
                clip.remove_notes_extended(pitch, 1, 0.0, clip.length)
            else:
                clip.remove_notes(0.0, pitch, clip.length, 1)

            if hasattr(clip, 'add_new_notes'):
                clip.add_new_notes(tuple(new_notes))
            else:
                old_notes = [(n.pitch, n.start_time, n.duration, n.velocity, n.mute) for n in new_notes]
                clip.set_notes(tuple(old_notes))

            self._log_info("Quantized drum %d to division %d" % (drum_index, division))
            self._cs.log_message("QUANT: Drum %d quantized to division %d" % (drum_index, division))
            self._invalidate_clip_cache()

        except Exception as e:
            self._log_error("_quantize_drum_notes", e)

    
    def _clear_drum_notes(self, drum_index):
        """Clear all notes for a specific drum."""
        try:
            if drum_index < 0 or drum_index >= len(self._row_note_offsets):
                return
            
            pitch = self._row_note_offsets[drum_index]
            clip = self._ensure_clip()
            if clip is None:
                return
            
            # Get all notes for this pitch
            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(pitch, 1, 0.0, clip.length)
            else:
                notes = clip.get_notes(0.0, pitch, clip.length, 1)
            
            if notes and len(notes) > 0:
                # Remove all notes
                if hasattr(clip, 'remove_notes_extended'):
                    clip.remove_notes_extended(pitch, 1, 0.0, clip.length)
                else:
                    clip.remove_notes(0.0, pitch, clip.length, 1)
                
                self._log_info("Cleared %d notes from drum %d (pitch %d)" % 
                             (len(notes), drum_index, pitch))
                self._cs.log_message("CLEAR: Removed %d notes from drum %d" % (len(notes), drum_index))
                
                # Invalidate clip cache so refresh_grid gets updated data
                self._invalidate_clip_cache()
            else:
                self._cs.log_message("CLEAR: Drum %d had no notes to clear" % drum_index)
            
        except Exception as e:
            self._log_error("_clear_drum_notes", e)
    
    def _copy_drum_notes(self, drum_index):
        """Copy all notes from a specific drum to buffer."""
        try:
            if drum_index < 0 or drum_index >= len(self._row_note_offsets):
                return
            
            pitch = self._row_note_offsets[drum_index]
            clip = self._ensure_clip()
            if clip is None:
                return
            
            # Get all notes for this pitch
            if hasattr(clip, 'get_notes_extended'):
                notes = clip.get_notes_extended(pitch, 1, 0.0, clip.length)
            else:
                notes = clip.get_notes(0.0, pitch, clip.length, 1)
            
            if notes and len(notes) > 0:
                # Store notes in buffer
                self._copied_notes = list(notes)
                self._log_info("Copied %d notes from drum %d (pitch %d)" % 
                             (len(notes), drum_index, pitch))
            else:
                self._log_info("No notes to copy from drum %d" % drum_index)
            
        except Exception as e:
            self._log_error("_copy_drum_notes", e)
    
    def _paste_drum_notes(self, drum_index):
        """Paste notes from buffer to a specific drum."""
        try:
            if not self._copied_notes:
                self._log_info("No notes in copy buffer")
                return
            
            if drum_index < 0 or drum_index >= len(self._row_note_offsets):
                return
            
            target_pitch = self._row_note_offsets[drum_index]
            clip = self._ensure_clip()
            if clip is None:
                return
            
            # Create new notes with target pitch using Live 12 API
            new_notes = []
            for note in self._copied_notes:
                if hasattr(note, 'pitch'):
                    # Live 11+ MidiNote object
                    note_spec = Live.Clip.MidiNoteSpecification(
                        pitch=int(target_pitch),
                        start_time=float(note.start_time),
                        duration=float(note.duration),
                        velocity=int(note.velocity),
                        mute=bool(note.mute) if hasattr(note, 'mute') else False
                    )
                else:
                    # Old API tuple
                    note_spec = Live.Clip.MidiNoteSpecification(
                        pitch=int(target_pitch),
                        start_time=float(note[1]),
                        duration=float(note[2]),
                        velocity=int(note[3]),
                        mute=bool(note[4]) if len(note) > 4 else False
                    )
                new_notes.append(note_spec)
            
            # Add notes to clip
            if hasattr(clip, 'add_new_notes'):
                clip.add_new_notes(tuple(new_notes))
            else:
                # Old API fallback
                old_notes = [(n.pitch, n.start_time, n.duration, n.velocity, n.mute) for n in new_notes]
                clip.set_notes(tuple(old_notes))
            
            self._log_info("Pasted %d notes to drum %d (pitch %d)" % 
                         (len(new_notes), drum_index, target_pitch))
            
            # Invalidate clip cache so refresh_grid gets updated data
            self._invalidate_clip_cache()
            
        except Exception as e:
            self._log_error("_paste_drum_notes", e)
    
    def _fill_drum_notes(self, drum_index, note_duration):
        """Fill a drum with notes at regular intervals."""
        try:
            if drum_index < 0 or drum_index >= len(self._row_note_offsets):
                return
            
            pitch = self._row_note_offsets[drum_index]
            clip = self._ensure_clip()
            if clip is None:
                return
            
            # Get loop length
            loop_length = self._loop_bars_options[self._loop_bars_index] * 4.0
            
            # Generate notes using Live 12 API
            new_notes = []
            time = 0.0
            velocity = self._drum_velocity[drum_index]
            
            while time < loop_length:
                note_spec = Live.Clip.MidiNoteSpecification(
                    pitch=int(pitch),
                    start_time=float(time),
                    duration=float(note_duration),
                    velocity=int(velocity),
                    mute=False
                )
                new_notes.append(note_spec)
                time += note_duration
            
            # Add notes to clip
            if hasattr(clip, 'add_new_notes'):
                clip.add_new_notes(tuple(new_notes))
            else:
                # Old API fallback
                old_notes = [(pitch, time, note_duration, velocity, False) for n in new_notes]
                clip.set_notes(tuple(old_notes))
            
            self._log_info("Filled drum %d with %d notes (duration=%.2f)" % 
                         (drum_index, len(new_notes), note_duration))
            
            # Invalidate clip cache so refresh_grid gets updated data
            self._invalidate_clip_cache()
            
        except Exception as e:
            self._log_error("_fill_drum_notes", e)
    
    def render_scene_function_leds(self, scene_launch_buttons):
        """
        Render scene launch button LEDs to show function assignments.
        
        Args:
            scene_launch_buttons: List of scene launch buttons
        """
        try:
            self._log_info("Rendering scene LEDs for %d buttons" % len(scene_launch_buttons))
            self._cs.log_message("Rendering scene LEDs for %d buttons" % len(scene_launch_buttons))
            
            for i, btn in enumerate(scene_launch_buttons):
                absolute_index = self._visible_to_absolute_drum(i)
                if absolute_index is None or absolute_index >= len(self._drum_functions):
                    self._log_info("Button %d: Out of range" % i)
                    continue
                
                func = self._drum_functions[absolute_index]
                color = self._function_colors.get(func, self._LED_OFF)
                
                self._log_info("Button %d (drum %d): func=%d, color=%d" % (i, absolute_index, func, color))
                self._cs.log_message("Button %d (drum %d): func=%d, color=%d" % (i, absolute_index, func, color))
                
                if btn and hasattr(btn, 'send_value'):
                    btn.send_value(color, True)  # True = force LED update
                    self._log_info("Button %d: LED set to color %d" % (i, color))
                    self._cs.log_message("Button %d: LED set to color %d (FORCED)" % (i, color))
                else:
                    self._log_info("Button %d: No send_value method!" % i)
                    self._cs.log_message("Button %d: No send_value method!" % i)
                    
        except Exception as e:
            self._log_error("render_scene_function_leds", e)
    
    def get_current_function_color(self):
        """Get the color for the currently selected function."""
        return self._function_colors.get(self._current_function, self._LED_OFF)
    
    def get_current_function_name(self):
        """Get the name of the currently selected function."""
        return self._function_names.get(self._current_function, "UNKNOWN")
    
    def start_scene_preview(self, function_color):
        """
        Start the scene preview animation.
        
        Args:
            function_color: Color to flash on all scene buttons
        """
        self._scene_preview_active = True
        self._scene_preview_color = function_color
        self._scene_preview_count = 0
        self._cs.log_message("Scene preview started: color=%d" % function_color)
    
    def update_scene_preview(self, scene_launch_buttons):
        """
        Update the scene preview animation (called every tick).
        
        Args:
            scene_launch_buttons: List of scene launch buttons
            
        Returns:
            bool: True if preview is still active, False if complete
        """
        if not self._scene_preview_active:
            return False
        
        try:
            # Increment blink count
            self._scene_preview_count += 1
            
            # Flash all scene buttons in the preview color (no OFF phase for faster feedback)
            for btn in scene_launch_buttons:
                if btn and hasattr(btn, 'send_value'):
                    btn.send_value(self._scene_preview_color, True)
            
            # Check if preview is complete (~1 second at 90ms/tick)
            if self._scene_preview_count >= self._scene_preview_target:
                self._scene_preview_active = False
                self._cs.log_message("Scene preview complete")
                
                # Restore individual drum function LEDs
                self.render_scene_function_leds(scene_launch_buttons)
                return False
            
            return True
            
        except Exception as e:
            self._log_error("update_scene_preview", e)
            self._scene_preview_active = False
            return False
