from __future__ import absolute_import, print_function, unicode_literals
import Live
from functools import partial
from .SequencerLogger import SequencerLogger
from .SequencerBase import SequencerBase
from .DrumSequencer import DrumSequencer
from .InstrumentSequencer import InstrumentSequencer
from .ClipSequencer import ClipSequencer
try:
    from .UserConfig import USE_SECOND_WINDOW_FOR_CLIP_VIEW
except Exception:
    USE_SECOND_WINDOW_FOR_CLIP_VIEW = False


class _ShiftResourceClient(object):

    def __init__(self, sequencer):
        self._sequencer = sequencer

    def set_control_element(self, control, *a, **k):
        try:
            self._sequencer._handle_shift_control_update(control)
        except Exception as exc:
            self._sequencer._logger.log_error("_ShiftResourceClient.set_control_element", exc)

class StepSequencer(object):
    """
    Main step sequencer coordinator.
    Detects clip type and delegates to appropriate sequencer component.
    """
    
    def __init__(self, control_surface, song, shift_button, user_button, pan_button, sends_button,
                 left_button, right_button, up_button, down_button,
                 scene_launch_buttons_raw, clip_stop_buttons_raw, matrix_rows_raw, knob_controls, track_select_buttons,
                 device_controls=None, prev_device_button=None, next_device_button=None, 
                 stop_all_button=None, master_button=None, bank_button=None, prehear_control=None):
        """
        Initialize the step sequencer coordinator.
        
        Args:
            control_surface: The main APC40 control surface instance
            song: The Live.Song.Song instance
            All button/control parameters for hardware mapping
        """
        self._cs = control_surface
        self._song = song
        
        # Initialize logger
        self._logger = SequencerLogger()
        self._logger.set_control_surface(control_surface)
        
        # Store hardware references
        self._shift_button = shift_button
        self._shift_client = _ShiftResourceClient(self) if shift_button else None
        self._shift_control = None
        self._shift_prev_owner = None
        self._user_button = user_button
        self._pan_button = pan_button
        self._sends_button = sends_button
        self._bank_button = bank_button
        self._left_button = left_button
        self._right_button = right_button
        self._up_button = up_button
        self._down_button = down_button
        self._scene_launch_buttons_raw = list(scene_launch_buttons_raw)
        self._stop_all_button = stop_all_button
        self._master_button = master_button
        
        # Log button initialization (both to logger and control surface)
        self._logger.log_info("Scene launch buttons: %d buttons" % len(self._scene_launch_buttons_raw))
        self._logger.log_info("Stop all button: %s" % (self._stop_all_button is not None))
        self._logger.log_info("Master button: %s" % (self._master_button is not None))
        
        # Also log directly to Ableton
        try:
            control_surface.log_message("StepSequencer: %d scene launch buttons" % len(self._scene_launch_buttons_raw))
        except Exception:
            pass
        
        # Normalize clip stop buttons into flat list
        try:
            raw = clip_stop_buttons_raw
            flattened = []
            for row in raw:
                if isinstance(row, (list, tuple)):
                    for btn in row:
                        flattened.append(btn)
                else:
                    flattened.append(row)
            self._clip_stop_buttons_raw = flattened
        except Exception:
            self._clip_stop_buttons_raw = list(clip_stop_buttons_raw) if clip_stop_buttons_raw else []
        
        self._matrix_rows_raw = [list(r) for r in matrix_rows_raw]
        self._knob_controls = list(knob_controls)
        self._track_select_buttons = list(track_select_buttons)
        self._device_controls = list(device_controls) if device_controls else []
        self._prev_device_button = prev_device_button
        self._next_device_button = next_device_button
        self._prehear_control = prehear_control
        
        # Initialize sequencer components
        self._drum_sequencer = DrumSequencer(control_surface, song, self._logger)
        self._instrument_sequencer = InstrumentSequencer(control_surface, song, self._logger)
        self._clip_sequencer = ClipSequencer(control_surface, song, self._logger)
        
        # Current active sequencer
        self._active_sequencer = None
        self._mode = False
        
        # Shift button state
        self._shift_is_pressed = False
        
        # Playhead tracking
        self._tick_task = None
        self._tick_interval = 1  # Dynamic, calculated based on tempo/note-length
        self._note_length_pending = False
        self._loop_length_pending = False
        self._note_length_timer = None
        self._loop_length_timer = None
        self._note_length_candidate = 0
        self._loop_bitmask = 0
        self._loop_bitmask_shift = 0
        self._loop_pending_shift = False
        self._note_length_generation = 0
        self._loop_length_generation = 0
        self._debounce_seconds = 0.3
        self._debounce_ticks = max(1, int(round(self._debounce_seconds / 0.03)))
        self._shift_resource = None
        self._note_length_candidate = 0
        self._base_note_length_count = 10
        
    # ==================== MODE DETECTION ====================
    
    def _detect_sequencer_mode(self):
        """
        Detect which sequencer mode to use based on clip type.
        
        Returns:
            SequencerBase: The appropriate sequencer component
        """
        try:
            self._logger.log_info("=== MODE DETECTION START ===")
            
            # First check for audio clip (AIF, WAV, etc.)
            self._logger.log_info("Checking for audio clip...")
            is_audio = self._clip_sequencer.detect_audio_clip()
            self._logger.log_info("Audio clip check result: %s" % is_audio)
            
            if is_audio:
                self._logger.log_info("Mode: Audio Clip (AIF/WAV detected)")
                return self._clip_sequencer
            
            # Check for drum rack
            track = self._song.view.selected_track
            if track and hasattr(track, 'devices'):
                for device in track.devices:
                    if hasattr(device, 'can_have_drum_pads') and device.can_have_drum_pads:
                        self._logger.log_info("Mode: Drum Rack")
                        return self._drum_sequencer
                    
                    # Check for Sampler/Simpler in drum mode
                    if hasattr(device, 'name'):
                        name = str(device.name).lower()
                        if 'sampler' in name or 'simpler' in name:
                            # Check if it's in drum mode
                            if hasattr(device, 'playback_mode'):
                                if device.playback_mode in [0, 1]:  # Classic or Slicing
                                    self._logger.log_info("Mode: Drum (Sampler/Simpler)")
                                    return self._drum_sequencer
            
            # Check if we have a MIDI clip at all
            self._logger.log_info("Checking for MIDI clip...")
            clip = self._drum_sequencer._ensure_clip()
            if not clip:
                self._logger.log_info("Mode: Melodic Instrument (no clip)")
                return self._instrument_sequencer
            
            # Check if clip has is_audio_clip property
            if hasattr(clip, 'is_audio_clip'):
                self._logger.log_info("Clip has is_audio_clip property: %s" % clip.is_audio_clip)
            else:
                self._logger.log_info("Clip does not have is_audio_clip property")
            
            # Check if clip has MIDI-related properties
            has_midi_methods = hasattr(clip, 'get_notes_extended') or hasattr(clip, 'get_notes')
            self._logger.log_info("Clip has MIDI methods: %s" % has_midi_methods)
            
            # For MIDI clips, analyze content to determine if it's a piano roll or drum pattern
            if clip and hasattr(clip, 'get_notes_extended'):
                try:
                    self._logger.log_info("Analyzing MIDI clip content...")
                    notes = clip.get_notes_extended(0, 127, 0.0, clip.length)
                    self._logger.log_info("Found %d notes in clip" % len(notes))
                    
                    if not notes:
                        # Empty MIDI clip - default to melodic instrument
                        self._logger.log_info("Mode: Melodic Instrument (empty MIDI clip)")
                        return self._instrument_sequencer
                    
                    pitches = set()
                    velocities = set()
                    start_times = set()
                    
                    for note in notes:
                        pitch = note.pitch if hasattr(note, 'pitch') else note[0]
                        velocity = note.velocity if hasattr(note, 'velocity') else note[3]
                        start = note.start_time if hasattr(note, 'start_time') else note[1]
                        
                        pitches.add(pitch)
                        velocities.add(velocity)
                        start_times.add(start)
                    
                    pitch_range = max(pitches) - min(pitches)
                    
                    # Check for piano roll characteristics:
                    # - Wide pitch range (>2 octaves)
                    # - Varied velocities
                    # - Melodic patterns (notes not aligned to grid)
                    is_piano_roll = False
                    
                    if pitch_range > 24:  # More than 2 octaves suggests piano roll
                        is_piano_roll = True
                        self._logger.log_info("Piano roll detected: wide pitch range (%d semitones)" % pitch_range)
                    
                    if len(velocities) > 4:  # Many velocity variations suggests piano roll
                        is_piano_roll = True
                        self._logger.log_info("Piano roll detected: varied velocities (%d unique)" % len(velocities))
                    
                    # Check for melodic patterns (notes not on strict grid)
                    grid_divisions = set()
                    for start in start_times:
                        # Quantize to 1/16th notes
                        grid_pos = round(start * 4) / 4
                        grid_divisions.add(grid_pos)
                    
                    if len(grid_divisions) > 8:  # Many unique positions suggests melodic
                        is_piano_roll = True
                        self._logger.log_info("Piano roll detected: melodic pattern (%d unique positions)" % len(grid_divisions))
                    
                    if is_piano_roll:
                        self._logger.log_info("Mode: Piano Roll (Melodic Instrument)")
                        return self._instrument_sequencer
                    
                    # Check for VERY LIMITED drum pattern (≤8 notes in ≤1 octave)
                    # Be conservative - only detect obvious drum patterns
                    if len(pitches) <= 8 and pitch_range <= 12:
                        self._logger.log_info("Mode: Drum (detected pattern: %d notes, %d semitone range)" % (len(pitches), pitch_range))
                        return self._drum_sequencer
                    else:
                        # Default to melodic for anything else (safer default)
                        self._logger.log_info("Mode: Melodic Instrument (%d notes, %d semitone range)" % (len(pitches), pitch_range))
                        return self._instrument_sequencer
                except Exception as e:
                    self._logger.log_error("Error analyzing clip content", e)
                    pass
            
            # Default to melodic instrument
            self._logger.log_info("Mode: Melodic Instrument (no clip data)")
            return self._instrument_sequencer
            
        except Exception as e:
            self._logger.log_error("_detect_sequencer_mode", e)
            return self._drum_sequencer  # Safe fallback
    
    # ==================== MODE MANAGEMENT ====================
    
    def _enter(self):
        """Enter step sequencer mode."""
        try:
            self._mode = True
            self._note_length_pending = False
            self._loop_length_pending = False
            self._note_length_timer = None
            self._loop_length_timer = None
            self._note_length_candidate = 0
            self._loop_bitmask = 0
            self._loop_bitmask_shift = 0
            self._loop_pending_shift = False
            self._note_length_generation += 1
            self._loop_length_generation += 1
            
            # Detect and activate appropriate sequencer
            self._active_sequencer = self._detect_sequencer_mode()
            if self._active_sequencer:
                self._active_sequencer.enter()
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                if isinstance(self._active_sequencer, ClipSequencer) and self._active_sequencer.is_audio_mode():
                    bank_active = getattr(self._active_sequencer, '_bank_mode', False)
                    self._active_sequencer.render_view_leds(self._track_select_buttons, bank_active)
                else:
                    self._active_sequencer._render_note_length_leds(self._track_select_buttons)
            self._update_loop_leds()
            if self._shift_button and hasattr(self._shift_button, 'resource'):
                try:
                    resource = self._shift_button.resource
                    owner = resource.owner
                    if owner not in (None, self._shift_client):
                        self._shift_prev_owner = owner
                    if self._shift_client is None:
                        self._shift_client = _ShiftResourceClient(self)
                    self._shift_resource = resource.grab(self._shift_client)
                except Exception as e:
                    self._logger.log_error("_enter(grab shift)", e)
            
            # Register button listeners
            self._register_button_listeners()
            
            # Add tempo listener for dynamic tick rate adjustment
            if hasattr(self._song, 'add_tempo_listener'):
                self._song.add_tempo_listener(self._on_tempo_changed)
            
            # Start playhead tracking
            self._schedule_tick()
            
            # Ensure Live marks the current clip as active and show Clip Detail view
            try:
                active = self._active_sequencer
                if active and hasattr(active, '_get_cached_clip') and hasattr(active, '_ensure_clip'):
                    clip = active._get_cached_clip() or active._ensure_clip()
                    if clip:
                        # Highlight clip slot so Live treats it as the active clip location
                        try:
                            slot = getattr(clip, 'canonical_parent', None)
                            if slot and hasattr(self._song.view, 'highlighted_clip_slot'):
                                self._song.view.highlighted_clip_slot = slot
                        except Exception as view_exc:
                            self._logger.log_error("_enter(highlighted_clip_slot)", view_exc)

                        # Focus the Detail view and select the Clip tab
                        try:
                            app = Live.Application.get_application()
                            if hasattr(app, 'view') and hasattr(app.view, 'show_view'):
                                if USE_SECOND_WINDOW_FOR_CLIP_VIEW:
                                    # Prefer second window first; fall back to primary
                                    tried_second = False
                                    try:
                                        app.view.show_view('Detail', True)
                                        tried_second = True
                                    except Exception:
                                        pass
                                    try:
                                        app.view.show_view('Detail/Clip', True)
                                        tried_second = True
                                    except Exception:
                                        pass
                                    if not tried_second:
                                        try:
                                            app.view.show_view('Detail')
                                        except Exception:
                                            pass
                                        try:
                                            app.view.show_view('Detail/Clip')
                                        except Exception:
                                            pass
                                else:
                                    try:
                                        app.view.show_view('Detail')
                                    except Exception:
                                        pass
                                    try:
                                        app.view.show_view('Detail/Clip')
                                    except Exception:
                                        pass
                        except Exception as show_exc:
                            self._logger.log_error("_enter(show_view)", show_exc)

                        # Assign the detail_clip to ensure the Clip view shows this clip
                        try:
                            if hasattr(self._song.view, 'detail_clip'):
                                self._song.view.detail_clip = clip
                        except Exception as dc_exc:
                            self._logger.log_error("_enter(detail_clip)", dc_exc)
            except Exception as e2:
                self._logger.log_error("_enter(activate_clip_view)", e2)

            self._logger.log_info("=== STEP SEQUENCER ENTERED ===")
            
        except Exception as e:
            self._logger.log_error("_enter", e)
    
    def _exit(self):
        """Exit step sequencer mode."""
        try:
            self._mode = False
            
            # Exit active sequencer
            if self._active_sequencer:
                self._active_sequencer.exit()
                self._active_sequencer._clear_all_leds(self._matrix_rows_raw)
                self._active_sequencer._clear_note_length_leds(self._track_select_buttons)
                if isinstance(self._active_sequencer, DrumSequencer):
                    try:
                        self._active_sequencer._clear_playhead_column(self._matrix_rows_raw)
                    except Exception as exc:
                        self._logger.log_error("_exit(clear_playhead)", exc)
            self._note_length_pending = False
            self._loop_length_pending = False
            self._note_length_timer = None
            self._loop_length_timer = None
            self._note_length_candidate = 0
            self._loop_bitmask = 0
            self._loop_bitmask_shift = 0
            self._loop_pending_shift = False
            self._note_length_generation += 1
            self._loop_length_generation += 1
            self._update_loop_leds()
            if self._shift_resource and hasattr(self._shift_button, 'resource'):
                try:
                    resource = self._shift_button.resource
                    resource.release(self._shift_client)
                    if self._shift_prev_owner:
                        try:
                            resource.grab(self._shift_prev_owner)
                        except Exception as exc:
                            self._logger.log_error("_exit(restore shift owner)", exc)
                    self._shift_prev_owner = None
                except Exception as e:
                    self._logger.log_error("_exit(release shift)", e)
                self._shift_resource = None
            self._detach_shift_control()
            
            # Unregister button listeners
            self._unregister_button_listeners()
            
            # Remove tempo listener
            if hasattr(self._song, 'remove_tempo_listener'):
                try:
                    self._song.remove_tempo_listener(self._on_tempo_changed)
                except Exception:
                    pass
            
            # Stop playhead tracking
            if self._tick_task:
                self._tick_task.kill()
                self._tick_task = None
            
            self._active_sequencer = None
            self._logger.log_info("=== STEP SEQUENCER EXITED ===")
            
        except Exception as e:
            self._logger.log_error("_exit", e)
    
    # ==================== BUTTON LISTENERS ====================
    
    def _register_button_listeners(self):
        """Register all button listeners."""
        try:
            # Navigation buttons
            if self._left_button:
                self._left_button.add_value_listener(self._on_left)
            if self._right_button:
                self._right_button.add_value_listener(self._on_right)
            if self._up_button:
                self._up_button.add_value_listener(self._on_up)
            if self._down_button:
                self._down_button.add_value_listener(self._on_down)
            
            # Shift button
            if self._shift_button:
                if hasattr(self._shift_button, 'resource'):
                    # Resource listener handled via _handle_shift_control_update
                    if not self._shift_resource:
                        try:
                            if self._shift_client is None:
                                self._shift_client = _ShiftResourceClient(self)
                            self._shift_resource = self._shift_button.resource.grab(self._shift_client)
                        except Exception as e:
                            self._logger.log_error("_register_button_listeners(grab shift)", e)
                elif not self._shift_button.value_has_listener(self._on_shift_value):
                    self._shift_button.add_value_listener(self._on_shift_value)
            
            # Matrix buttons
            for row in self._matrix_rows_raw:
                for btn in row:
                    if btn:
                        btn.add_value_listener(self._on_matrix_button, identify_sender=True)
            
            # Track select buttons (note length)
            # Store listeners to prevent duplicates and allow cleanup
            if not hasattr(self, '_track_select_listeners'):
                self._track_select_listeners = []
            for i, btn in enumerate(self._track_select_buttons):
                if btn:
                    listener = lambda v, idx=i: self._on_track_select(idx, v)
                    self._track_select_listeners.append((btn, listener))
                    btn.add_value_listener(listener)
            
            # Clip stop buttons (loop length)
            for btn in self._clip_stop_buttons_raw:
                if btn:
                    btn.add_value_listener(self._on_clip_stop_button, identify_sender=True)
            
            # Scene launch buttons (function assignment)
            self._logger.log_info("Registering %d scene launch button listeners" % len(self._scene_launch_buttons_raw))
            self._cs.log_message("Registering %d scene launch button listeners" % len(self._scene_launch_buttons_raw))
            for i, btn in enumerate(self._scene_launch_buttons_raw):
                if btn:
                    btn.add_value_listener(lambda v, idx=i: self._on_scene_launch_button(idx, v))
                    self._logger.log_info("Registered listener for scene button %d" % i)
                    self._cs.log_message("Registered listener for scene button %d" % i)
                else:
                    self._logger.log_info("Scene button %d is None!" % i)
                    self._cs.log_message("Scene button %d is None!" % i)
            
            # Stop all button (function selection)
            if self._stop_all_button:
                self._stop_all_button.add_value_listener(self._on_stop_all_button)
            
            # Master button (function execution)
            if self._master_button:
                self._master_button.add_value_listener(self._on_master_button)
            
            # Bank button (ALT mode)
            if self._bank_button:
                self._bank_button.add_value_listener(self._on_bank_button)
            
            # Device knobs
            for i, knob in enumerate(self._device_controls):
                if knob:
                    knob.add_value_listener(lambda v, idx=i: self._on_device_knob_value(idx, v))
            
            # Assignable knobs
            for i, knob in enumerate(self._knob_controls):
                if knob:
                    knob.add_value_listener(lambda v, idx=i: self._on_knob_value(idx, v))
            
        except Exception as e:
            self._logger.log_error("_register_button_listeners", e)
    
    def _unregister_button_listeners(self):
        """Unregister all button listeners."""
        try:
            # Navigation buttons
            if self._left_button and self._left_button.value_has_listener(self._on_left):
                self._left_button.remove_value_listener(self._on_left)
            if self._right_button and self._right_button.value_has_listener(self._on_right):
                self._right_button.remove_value_listener(self._on_right)
            if self._up_button and self._up_button.value_has_listener(self._on_up):
                self._up_button.remove_value_listener(self._on_up)
            if self._down_button and self._down_button.value_has_listener(self._on_down):
                self._down_button.remove_value_listener(self._on_down)
            
            # Shift button
            if self._shift_button:
                if hasattr(self._shift_button, 'resource'):
                    self._detach_shift_control()
                    if self._shift_resource:
                        try:
                            resource = self._shift_button.resource
                            resource.release(self._shift_client)
                            if self._shift_prev_owner:
                                try:
                                    resource.grab(self._shift_prev_owner)
                                except Exception as exc:
                                    self._logger.log_error("_unregister_button_listeners(restore shift owner)", exc)
                            self._shift_prev_owner = None
                        except Exception as e:
                            self._logger.log_error("_unregister_button_listeners(release shift)", e)
                        self._shift_resource = None
                elif self._shift_button.value_has_listener(self._on_shift_value):
                    self._shift_button.remove_value_listener(self._on_shift_value)
            
            # Matrix buttons
            for row in self._matrix_rows_raw:
                for btn in row:
                    if btn and btn.value_has_listener(self._on_matrix_button):
                        btn.remove_value_listener(self._on_matrix_button)
            
            # Track select buttons
            if hasattr(self, '_track_select_listeners'):
                for btn, listener in self._track_select_listeners:
                    try:
                        if btn and btn.value_has_listener(listener):
                            btn.remove_value_listener(listener)
                    except Exception as exc:
                        self._logger.log_error("_unregister_button_listeners(track_select)", exc)
                self._track_select_listeners = []
            
            # Clip stop buttons
            for btn in self._clip_stop_buttons_raw:
                if btn and btn.value_has_listener(self._on_clip_stop_button):
                    btn.remove_value_listener(self._on_clip_stop_button)
            
            # Scene launch buttons
            for i, btn in enumerate(self._scene_launch_buttons_raw):
                # Lambda listeners can't be checked easily, so just try to remove
                pass
            
        except Exception as e:
            self._logger.log_error("_unregister_button_listeners", e)

    def _handle_shift_control_update(self, control):
        try:
            if self._shift_control is control:
                return
            self._detach_shift_control()
            self._shift_control = control
            if self._shift_control and not self._shift_control.value_has_listener(self._on_shift_value):
                self._shift_control.add_value_listener(self._on_shift_value)
        except Exception as exc:
            self._logger.log_error("_handle_shift_control_update", exc)

    def _detach_shift_control(self):
        try:
            if self._shift_control and self._shift_control.value_has_listener(self._on_shift_value):
                self._shift_control.remove_value_listener(self._on_shift_value)
        except Exception as exc:
            self._logger.log_error("_detach_shift_control", exc)
        finally:
            self._shift_control = None

    # ==================== BUTTON HANDLERS ====================
    
    def _on_left(self, value):
        """Handle left button press."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            if isinstance(self._active_sequencer, DrumSequencer):
                # If currently on right boundary virtual column, clear it first
                if getattr(self._active_sequencer, '_x_boundary_offset', 0) == 1:
                    self._active_sequencer._x_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Left: cleared right boundary overlay")
                elif self._active_sequencer._time_page > 0:
                    self._active_sequencer._time_page -= 1
                    self._active_sequencer._x_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False  # Clear warning on successful nav
                    self._active_sequencer._clear_boundary_leds(self._matrix_rows_raw)
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Left: time_page=%d" % self._active_sequencer._time_page)
                else:
                    # At left boundary: enter virtual left column or blink if already there
                    if getattr(self._active_sequencer, '_x_boundary_offset', 0) == -1:
                        self._active_sequencer.trigger_boundary_warning('left')
                    else:
                        self._active_sequencer._x_boundary_offset = -1
                        self._active_sequencer._boundary_direction = 'left'
                        self._active_sequencer._boundary_warning_active = True
                        self._active_sequencer._boundary_blinking = False
                        self._active_sequencer._boundary_blink_count = 0
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Left: at left boundary (virtual column)")
            else:
                if self._active_sequencer.navigate_left():
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_on_left", e)
    
    def _on_right(self, value):
        """Handle right button press."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            if isinstance(self._active_sequencer, DrumSequencer):
                # Calculate if we can navigate right
                loop_length = self._active_sequencer._loop_bars_options[self._active_sequencer._loop_bars_index] * 4.0
                note_len = self._active_sequencer._note_lengths[self._active_sequencer._note_length_index]
                next_page_start = (self._active_sequencer._time_page + 1) * self._active_sequencer._steps_per_page * note_len
                
                # If currently on left boundary virtual column, clear it first
                if getattr(self._active_sequencer, '_x_boundary_offset', 0) == -1:
                    self._active_sequencer._x_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Right: cleared left boundary overlay")
                elif next_page_start < loop_length:
                    self._active_sequencer._time_page += 1
                    self._active_sequencer._x_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False  # Clear warning on successful nav
                    self._active_sequencer._clear_boundary_leds(self._matrix_rows_raw)
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Right: time_page=%d" % self._active_sequencer._time_page)
                else:
                    # At right boundary: enter virtual right column or blink if already there
                    if getattr(self._active_sequencer, '_x_boundary_offset', 0) == 1:
                        self._active_sequencer.trigger_boundary_warning('right')
                    else:
                        self._active_sequencer._x_boundary_offset = 1
                        self._active_sequencer._boundary_direction = 'right'
                        self._active_sequencer._boundary_warning_active = True
                        self._active_sequencer._boundary_blinking = False
                        self._active_sequencer._boundary_blink_count = 0
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Right: at right boundary (virtual column)")
            else:
                if self._active_sequencer.navigate_right():
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_on_right", e)
    
    def _on_up(self, value):
        """Handle up button press."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            if isinstance(self._active_sequencer, InstrumentSequencer):
                if self._active_sequencer.navigate_up():
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
            elif isinstance(self._active_sequencer, DrumSequencer):
                # If currently on bottom boundary virtual row, clear it first
                if getattr(self._active_sequencer, '_y_boundary_offset', 0) == 1:
                    self._active_sequencer._y_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Up: cleared bottom boundary overlay")
                elif self._active_sequencer._drum_row_base > 0:
                    self._active_sequencer._drum_row_base -= 1
                    self._active_sequencer._y_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False  # Clear warning on successful nav
                    self._active_sequencer._clear_boundary_leds(self._matrix_rows_raw)
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Up: drum_row_base=%d" % self._active_sequencer._drum_row_base)
                else:
                    # At top boundary: enter virtual top row or blink if already there
                    if getattr(self._active_sequencer, '_y_boundary_offset', 0) == -1:
                        self._active_sequencer.trigger_boundary_warning('up')
                    else:
                        self._active_sequencer._y_boundary_offset = -1
                        self._active_sequencer._boundary_direction = 'up'
                        self._active_sequencer._boundary_warning_active = True
                        self._active_sequencer._boundary_blinking = False
                        self._active_sequencer._boundary_blink_count = 0
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Up: at top boundary (virtual row)")
        except Exception as e:
            self._logger.log_error("_on_up", e)
    
    def _on_down(self, value):
        """Handle down button press."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            if isinstance(self._active_sequencer, InstrumentSequencer):
                if self._active_sequencer.navigate_down():
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
            elif isinstance(self._active_sequencer, DrumSequencer):
                # Check boundary: only allow scrolling if not at bottom
                max_base = len(self._active_sequencer._row_note_offsets) - self._active_sequencer._rows_visible
                if getattr(self._active_sequencer, '_y_boundary_offset', 0) == -1:
                    # Clear top boundary overlay first
                    self._active_sequencer._y_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Down: cleared top boundary overlay")
                elif self._active_sequencer._drum_row_base < max(0, max_base - 1):  # Allow one more step before boundary
                    self._active_sequencer._drum_row_base += 1
                    self._active_sequencer._y_boundary_offset = 0
                    self._active_sequencer._boundary_warning_active = False  # Clear warning on successful nav
                    self._active_sequencer._clear_boundary_leds(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Down: drum_row_base=%d (max=%d)" % (self._active_sequencer._drum_row_base, max_base))
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                else:
                    # At bottom boundary: enter virtual bottom row or blink if already there
                    if getattr(self._active_sequencer, '_y_boundary_offset', 0) == 1:
                        self._active_sequencer.trigger_boundary_warning('down')
                    else:
                        self._active_sequencer._y_boundary_offset = 1
                        self._active_sequencer._boundary_direction = 'down'
                        self._active_sequencer._boundary_warning_active = True
                        self._active_sequencer._boundary_blinking = False
                        self._active_sequencer._boundary_blink_count = 0
                    self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                    self._logger.log('NAVIGATION', "Down: at bottom boundary (virtual row)")
        except Exception as e:
            self._logger.log_error("_on_down", e)
    
    def _on_shift_value(self, value):
        """Handle shift button press."""
        try:
            self._shift_is_pressed = bool(value > 0)
            self._logger.log('BUTTON_PRESS', "Shift state changed: %s" % self._shift_is_pressed)
            # Invalidate pending actions and refresh LEDs for current modifier state
            self._note_length_pending = False
            self._loop_length_pending = False
            self._note_length_generation += 1
            self._loop_length_generation += 1
            self._update_loop_leds()
        except Exception as e:
            self._logger.log_error("_on_shift_value", e)
    
    def _on_matrix_button(self, value, sender=None):
        """Handle matrix button press."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            pos = self._active_sequencer._locate_matrix_button(sender, self._matrix_rows_raw)
            if pos:
                col, row = pos
                
                # Audio clip mode has different behavior
                if isinstance(self._active_sequencer, ClipSequencer):
                    if row == 2:  # Warp marker row
                        self._active_sequencer.toggle_warp_marker(col)
                    # Other rows handle loop start/end
                else:
                    # Drum or instrument mode - toggle note
                    self._active_sequencer.toggle_note(col, row, self._matrix_rows_raw)
                
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_on_matrix_button", e)
    
    def _on_track_select(self, track_index, value):
        """Handle track select button (note length)."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            # Log which sequencer type is active
            sequencer_type = type(self._active_sequencer).__name__
            self._logger.log('BUTTON_PRESS', "Track select pressed: index=%d shift=%s sequencer=%s" % (track_index, self._shift_is_pressed, sequencer_type))
            
            # Handle audio clip mode view controls
            if isinstance(self._active_sequencer, ClipSequencer) and self._active_sequencer.is_audio_mode():
                persistent_bank = getattr(self._active_sequencer, '_bank_mode', False)
                bank_effective = persistent_bank or self._shift_is_pressed
                self._logger.log('BUTTON_PRESS', "Audio view button pressed: index=%d shift=%s bank_state=%s" % (track_index, self._shift_is_pressed, persistent_bank))
                self._logger.log('AUDIO_SAMPLE', "Audio view mode request: index=%d bank_effective=%s" % (track_index, bank_effective))
                self._active_sequencer.set_view_mode(track_index, bank_pressed=bank_effective)
                self._active_sequencer.render_view_leds(self._track_select_buttons, bank_effective)
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                return

            if self._active_sequencer is None:
                return

            TOGGLE_TRIPLET = -1
            TOGGLE_SEPTUPLET = -2

            base_map = [0, 1, 2, 3, 4, 5, 6, 7]
            shift_map = [TOGGLE_TRIPLET, 7, 6, 5, 4, 8, 9, TOGGLE_SEPTUPLET]
            mapping = shift_map if self._shift_is_pressed else base_map
            if track_index >= len(mapping):
                return

            mapped_index = mapping[track_index]
            if mapped_index == TOGGLE_TRIPLET:
                self._toggle_triplet_mode()
                return
            if mapped_index == TOGGLE_SEPTUPLET:
                self._toggle_septuplet_mode()
                return

            if mapped_index >= 0:
                self._note_length_candidate = mapped_index
            else:
                clip = self._active_sequencer._get_cached_clip()
                if clip:
                    clip_length_beats = float(clip.loop_end - clip.loop_start)
                    if clip_length_beats > 0:
                        note_length = clip_length_beats
                        if note_length not in self._active_sequencer._note_lengths:
                            self._active_sequencer._note_lengths.append(note_length)
                        self._note_length_candidate = self._active_sequencer._note_lengths.index(note_length)
            
            # Apply note length immediately for all modes (drum, instrument, clip)
            self._note_length_pending = True
            self._note_length_generation += 1
            self._note_length_pending_shift = self._shift_is_pressed
            generation = self._note_length_generation
            
            if self._shift_is_pressed:
                self._apply_pending_note_length(generation, True)
            else:
                self._cs.schedule_message(self._debounce_ticks, partial(self._apply_pending_note_length, generation, False))
            
            self._update_note_length_leds_special()
        except Exception as e:
            self._logger.log_error("_on_track_select", e)

    def _apply_pending_note_length(self, generation, shift_snapshot):
        try:
            if generation != self._note_length_generation:
                self._logger.log('NOTE_LENGTH', "Skipped: generation mismatch")
                return
            if not self._note_length_pending or self._active_sequencer is None:
                self._logger.log('NOTE_LENGTH', "Skipped: not pending or no sequencer")
                return
            candidate = self._note_length_candidate
            if candidate >= len(self._active_sequencer._note_lengths):
                self._logger.log('NOTE_LENGTH', "Skipped: candidate %d out of range (max %d)" % (candidate, len(self._active_sequencer._note_lengths)))
                return
            
            sequencer_type = type(self._active_sequencer).__name__
            self._logger.log('NOTE_LENGTH', "Applying to %s: index=%d" % (sequencer_type, candidate))
            
            self._active_sequencer._note_length_index = candidate
            self._active_sequencer._current_note_length = self._active_sequencer._note_lengths[candidate]
            self._logger.log('NOTE_LENGTH', "Applied note length index=%d length=%.3f to %s" % (candidate, self._active_sequencer._current_note_length, sequencer_type))
            # Reset playhead and boundary/blink states to avoid phantom LEDs after note-length change
            try:
                seq = self._active_sequencer
                if hasattr(seq, '_clear_playhead_column'):
                    seq._clear_playhead_column(self._matrix_rows_raw)
                if hasattr(seq, '_last_blink_col'):
                    seq._last_blink_col = None
                if hasattr(seq, '_blink_phase'):
                    seq._blink_phase = 0
                if hasattr(seq, '_reset_grid_blink_states'):
                    seq._reset_grid_blink_states()
                if hasattr(seq, '_x_boundary_offset'):
                    seq._x_boundary_offset = 0
                if hasattr(seq, '_y_boundary_offset'):
                    seq._y_boundary_offset = 0
                if hasattr(seq, '_boundary_warning_active'):
                    seq._boundary_warning_active = False
                # Also reset playhead trail and cache to avoid artifacts when changing micro lengths
                try:
                    if hasattr(seq, '_last_trail_cols'):
                        seq._last_trail_cols = []
                    if hasattr(seq, '_last_step_idx'):
                        seq._last_step_idx = None
                    if hasattr(seq, '_playhead_cache'):
                        seq._playhead_cache = None
                except Exception:
                    pass
            except Exception as reset_exc:
                self._logger.log_error("_apply_pending_note_length(reset_states)", reset_exc)
            self._active_sequencer._render_note_length_leds(self._track_select_buttons)
            self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        finally:
            self._note_length_pending = False
            self._update_note_length_leds_special()

    def _toggle_triplet_mode(self):
        try:
            active = self._active_sequencer
            if not active:
                return
            active._triplet_mode = not active._triplet_mode
            if active._triplet_mode:
                active._septuplet_mode = False
            self._logger.log('NOTE_LENGTH', "Triplet mode %s" % ('ON' if active._triplet_mode else 'OFF'))
            self._propagate_subdivision_mode()
        except Exception as exc:
            self._logger.log_error("_toggle_triplet_mode", exc)

    def _toggle_septuplet_mode(self):
        try:
            active = self._active_sequencer
            if not active:
                return
            active._septuplet_mode = not active._septuplet_mode
            if active._septuplet_mode:
                active._triplet_mode = False
            self._logger.log('NOTE_LENGTH', "Septuplet mode %s" % ('ON' if active._septuplet_mode else 'OFF'))
            self._propagate_subdivision_mode()
        except Exception as exc:
            self._logger.log_error("_toggle_septuplet_mode", exc)

    def _propagate_subdivision_mode(self):
        try:
            active = self._active_sequencer
            if not active:
                return
            if hasattr(active, 'apply_subdivision_mode'):
                active.apply_subdivision_mode()
            active._render_note_length_leds(self._track_select_buttons)
            self._update_note_length_leds_special()
            active.refresh_grid(self._matrix_rows_raw)
        except Exception as exc:
            self._logger.log_error("_propagate_subdivision_mode", exc)

    def _update_note_length_leds_special(self):
        try:
            active = self._active_sequencer
            if not active:
                return
            if hasattr(active, '_render_note_length_leds'):
                active._render_note_length_leds(self._track_select_buttons)
            lime = getattr(active, '_LED_LIME', 0)
            triplet_color = getattr(active, '_LED_BLUE', 0)
            septuplet_color = getattr(active, '_LED_PURPLE', 0)
            pending_button = None
            if self._note_length_pending:
                pending_button = active.get_button_index_for_length(self._note_length_candidate)

            for idx, btn in enumerate(self._track_select_buttons):
                if not btn or not hasattr(btn, 'send_value'):
                    continue
                if self._note_length_pending and pending_button is not None and idx == pending_button:
                    btn.send_value(lime)
                    continue
                if active._triplet_mode and idx == 0:
                    btn.send_value(triplet_color)
                    continue
                if active._septuplet_mode and idx == 7:
                    btn.send_value(septuplet_color)
                    continue
        except Exception as exc:
            self._logger.log_error("_update_note_length_leds_special", exc)

    def _on_clip_stop_button(self, value, sender=None):
        """Handle clip stop button (loop length)."""
        if not value or not self._mode or not self._active_sequencer:
            return
        try:
            if sender in self._clip_stop_buttons_raw:
                idx = self._clip_stop_buttons_raw.index(sender)
                self._logger.log('BUTTON_PRESS', "Clip stop pressed: index=%d shift=%s" % (idx, self._shift_is_pressed))
                bit = 1 << idx
                if self._shift_is_pressed:
                    self._loop_bitmask_shift ^= bit
                else:
                    self._loop_bitmask ^= bit
                self._loop_length_pending = True
                self._loop_pending_shift = self._shift_is_pressed
                self._loop_length_generation += 1
                generation = self._loop_length_generation
                self._update_loop_leds()
                self._cs.schedule_message(self._debounce_ticks, partial(self._apply_pending_loop_length, generation))
        except Exception as e:
            self._logger.log_error("_on_clip_stop_button", e)

    def _apply_pending_loop_length(self, generation):
        try:
            if generation != self._loop_length_generation:
                return
            if not self._loop_length_pending or self._active_sequencer is None:
                return
            shift_flag = self._loop_pending_shift
            active_mask = self._loop_bitmask_shift if shift_flag else self._loop_bitmask
            total = 0
            for i in range(len(self._clip_stop_buttons_raw)):
                if active_mask & (1 << i):
                    total += 1 << i
            if total <= 0:
                return
            if total not in self._active_sequencer._loop_bars_options:
                self._active_sequencer._loop_bars_options.append(total)
            idx = self._active_sequencer._loop_bars_options.index(total)
            self._active_sequencer._loop_bars_index = idx
            self._logger.log('LOOP_LENGTH', "Applied loop length=%d bars" % total)
            self._active_sequencer._apply_loop_length()
            self._active_sequencer.refresh_grid(self._matrix_rows_raw)
            self._update_loop_leds()
        finally:
            self._loop_length_pending = False

    def _update_loop_leds(self):
        try:
            active_mask = self._loop_bitmask_shift if self._shift_is_pressed else self._loop_bitmask
            for i, btn in enumerate(self._clip_stop_buttons_raw):
                if not btn:
                    continue
                try:
                    value = 127 if (active_mask & (1 << i)) else 0
                    if hasattr(btn, 'send_value'):
                        btn.send_value(value, True)
                except Exception:
                    continue
        except Exception as e:
            self._logger.log_error("_update_loop_leds", e)
    
    def _on_scene_launch_button(self, button_index, value):
        """Handle scene launch button (function assignment for drums)."""
        self._logger.log('BUTTON_PRESS', "Scene launch button %d pressed (value=%d, mode=%s)" % 
                        (button_index, value, self._mode))
        self._cs.log_message("Scene launch button %d pressed (value=%d, mode=%s)" % 
                            (button_index, value, self._mode))
        
        if not value or not self._mode:
            self._cs.log_message("Scene button %d: Early return (value=%d, mode=%s)" % (button_index, value, self._mode))
            return
        
        self._cs.log_message("Scene button %d: Passed early return check" % button_index)
        
        try:
            self._cs.log_message("Active sequencer type: %s" % type(self._active_sequencer).__name__)
            
            if isinstance(self._active_sequencer, DrumSequencer):
                self._cs.log_message("In drum mode - toggling function for drum %d" % button_index)
                self._logger.log('FUNCTIONS', "Toggling drum function for drum %d" % button_index)
                self._active_sequencer.toggle_drum_function(button_index)
                self._active_sequencer.render_scene_function_leds(self._scene_launch_buttons_raw)
                self._cs.log_message("Function toggle complete")
            else:
                self._cs.log_message("Not in drum mode - active sequencer: %s" % 
                               type(self._active_sequencer).__name__)
                self._logger.log('BUTTON_PRESS', "Not in drum mode - active sequencer: %s" % 
                               type(self._active_sequencer).__name__)
        except Exception as e:
            self._cs.log_message("ERROR in scene launch handler: %s" % str(e))
            self._logger.log_error("_on_scene_launch_button", e)
    
    def _on_stop_all_button(self, value):
        """Handle stop all button (function selection for drums)."""
        self._logger.log('BUTTON_PRESS', "Stop all button pressed (value=%d, mode=%s)" % 
                        (value, self._mode))
        
        if not value or not self._mode:
            return
        try:
            if isinstance(self._active_sequencer, DrumSequencer):
                self._logger.log('FUNCTIONS', "Cycling function")
                self._active_sequencer.cycle_function()
                
                # Get the new function color
                color = self._active_sequencer.get_current_function_color()
                
                # Update master button LED
                if self._master_button:
                    self._master_button.send_value(color)
                    self._logger.log('FUNCTIONS', "Master button LED updated to color %d" % color)
                
                # Start scene preview animation
                self._active_sequencer.start_scene_preview(color)
                self._cs.log_message("Stop All: Starting scene preview for function color %d" % color)
            else:
                self._logger.log('BUTTON_PRESS', "Not in drum mode - active sequencer: %s" % 
                               type(self._active_sequencer).__name__)
        except Exception as e:
            self._logger.log_error("_on_stop_all_button", e)
    
    def _on_master_button(self, value):
        """Handle master button (function execution for drums)."""
        if not value or not self._mode:
            return
        try:
            if isinstance(self._active_sequencer, DrumSequencer):
                self._cs.log_message("Master button: Executing function")
                count = self._active_sequencer.execute_function()
                self._cs.log_message("Master button: Executed on %d drums" % count)
                
                # Blink feedback
                if count > 0:
                    # Success - 3 blinks
                    self._blink_button(self._master_button, 3)
                else:
                    # No drums assigned - 5 blinks
                    self._blink_button(self._master_button, 5)
                
                # Refresh grid and scene LEDs
                self._cs.log_message("Master button: Refreshing grid")
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
                self._cs.log_message("Master button: Rendering scene LEDs")
                self._active_sequencer.render_scene_function_leds(self._scene_launch_buttons_raw)
                self._cs.log_message("Master button: Complete")

                # Ensure clip detail view remains visible after drum functions
                clip = self._active_sequencer._get_cached_clip()
                if clip:
                    try:
                        if hasattr(self._song.view, 'detail_clip'):
                            self._song.view.detail_clip = clip
                        try:
                            app = Live.Application.get_application()
                            if hasattr(app, 'view') and hasattr(app.view, 'show_view'):
                                if USE_SECOND_WINDOW_FOR_CLIP_VIEW:
                                    tried_second = False
                                    try:
                                        app.view.show_view('Detail', True)
                                        tried_second = True
                                    except Exception:
                                        pass
                                    try:
                                        app.view.show_view('Detail/Clip', True)
                                        tried_second = True
                                    except Exception:
                                        pass
                                    if not tried_second:
                                        try:
                                            app.view.show_view('Detail')
                                        except Exception:
                                            pass
                                        try:
                                            app.view.show_view('Detail/Clip')
                                        except Exception:
                                            pass
                                else:
                                    try:
                                        app.view.show_view('Detail')
                                    except Exception:
                                        pass
                                    try:
                                        app.view.show_view('Detail/Clip')
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception as e:
            self._cs.log_message("Master button ERROR: %s" % str(e))
            self._logger.log_error("_on_master_button", e)
    
    def _on_bank_button(self, value):
        """Handle bank button (ALT mode)."""
        if not value or not self._mode:
            return
        try:
            if isinstance(self._active_sequencer, ClipSequencer) and self._active_sequencer.is_audio_mode():
                bank_active = self._active_sequencer.toggle_bank_mode()
                self._active_sequencer.render_view_leds(self._track_select_buttons, bank_active)
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_on_bank_button", e)
    
    def _on_device_knob_value(self, knob_index, value, sender=None):
        """Handle device knob value change."""
        if not self._mode or not self._active_sequencer:
            return
        try:
            # Device knobs can control velocity, pressure, etc.
            pass
        except Exception as e:
            self._logger.log_error("_on_device_knob_value", e)
    
    def _on_knob_value(self, knob_index, value, sender=None):
        """Handle assignable knob value change."""
        if not self._mode or not self._active_sequencer:
            return
        try:
            # Assignable knobs can control pitch, slide, etc.
            pass
        except Exception as e:
            self._logger.log_error("_on_knob_value", e)
    
    # ==================== PLAYHEAD TRACKING ====================
    
    def _on_tempo_changed(self):
        """Handle tempo changes to update tick interval."""
        try:
            # Tick interval will be recalculated on next _schedule_tick() call
            self._logger.log('TIMING', "Tempo changed to %.1f BPM" % self._song.tempo)
        except Exception as e:
            self._logger.log_error("_on_tempo_changed", e)
    
    def _calculate_tick_interval(self):
        """
        Calculate optimal tick interval based on tempo and note length.
        Aims for 8-10 updates per note to ensure smooth playhead tracking.
        Returns number of schedule_message ticks (~30ms each).
        """
        try:
            if not self._active_sequencer:
                return 1
            
            tempo = float(getattr(self._song, 'tempo', 120.0))
            note_len = self._active_sequencer._note_lengths[self._active_sequencer._note_length_index]
            # Force fastest tick for micro subdivisions to keep playhead smooth
            if note_len <= 0.125:  # 1/32 and smaller
                return 1
            
            # Calculate note duration in seconds
            # 1 beat = 60/tempo seconds
            beat_duration = 60.0 / tempo
            note_duration_sec = beat_duration * note_len
            
            # Target 8-10 updates per note for smooth tracking
            target_updates = 8.0
            target_interval_sec = note_duration_sec / target_updates
            
            # Convert to ticks (30ms each)
            tick_30ms = 0.030
            ticks = max(1, int(round(target_interval_sec / tick_30ms)))
            
            # Clamp to reasonable range: 1-3 ticks (30ms-90ms)
            ticks = max(1, min(3, ticks))
            
            # Log calculation periodically for debugging
            updates_per_note = note_duration_sec / (ticks * tick_30ms)
            self._logger.log('TIMING', "Tick interval: %d ticks (%.0fms) @ %.1f BPM, note=%.3f beats → %.1f updates/note" % 
                           (ticks, ticks * 1000 * tick_30ms, tempo, note_len, updates_per_note))
            
            return ticks
        except Exception as e:
            self._logger.log_error("_calculate_tick_interval", e)
            return 1  # Fast default
    
    def _schedule_tick(self):
        """Schedule the next tick for playhead tracking."""
        try:
            if self._mode:
                # Recalculate tick interval dynamically
                self._tick_interval = self._calculate_tick_interval()
                self._tick_task = self._cs.schedule_message(self._tick_interval, self._on_tick)
        except Exception as e:
            self._logger.log_error("_schedule_tick", e)
    
    def _on_tick(self):
        """Handle tick for playhead tracking and scene preview animation."""
        try:
            if self._mode and self._active_sequencer:
                # Micro-length throttle to prioritize playhead smoothness (<= 1/32)
                try:
                    note_len = self._active_sequencer._note_lengths[self._active_sequencer._note_length_index]
                except Exception:
                    note_len = 1.0
                micro = note_len <= 0.125
                if not hasattr(self, '_micro_tick_ctr'):
                    self._micro_tick_ctr = 0
                self._micro_tick_ctr = (self._micro_tick_ctr + 1) % 1024

                # Update scene preview animation (if active)
                if isinstance(self._active_sequencer, DrumSequencer):
                    if not micro or (self._micro_tick_ctr % 4 == 0):
                        self._active_sequencer.update_scene_preview(self._scene_launch_buttons_raw)

                # Advance any registered grid blink patterns
                if not micro or (self._micro_tick_ctr % 2 == 0):
                    try:
                        self._active_sequencer.advance_grid_blink(self._matrix_rows_raw)
                        self._logger.log('TIMING', "Grid blink advanced for active sequencer")
                    except Exception as blink_exc:
                        self._logger.log_error("_on_tick(advance_grid_blink)", blink_exc)

                # Update playhead visualization for drum mode (always)
                if isinstance(self._active_sequencer, DrumSequencer):
                    try:
                        # Force update playhead and clip stop buttons on every tick
                        # regardless of micro timing
                        self._active_sequencer.update_playhead_leds(
                            self._matrix_rows_raw,
                            self._clip_stop_buttons_raw
                        )
                        # Log playhead update for debugging
                        self._logger.log('PLAYHEAD', 'Updated playhead and clip stop LEDs')
                    except Exception as exc:
                        self._logger.log_error("_on_tick(update_playhead)", exc)
                    
                    # Update boundary warning animation (blinks RED on boundaries)
                    if self._active_sequencer._boundary_warning_active and (not micro or (self._micro_tick_ctr % 4 == 0)):
                        try:
                            self._active_sequencer._draw_boundary_warning(self._matrix_rows_raw)
                        except Exception as exc:
                            self._logger.log_error("_on_tick(boundary_warning)", exc)

                    # Re-assert static boundary bars so they persist during ticks
                    if not micro or (self._micro_tick_ctr % 4 == 0):
                        try:
                            self._active_sequencer._draw_static_boundaries(self._matrix_rows_raw)
                        except Exception as exc:
                            self._logger.log_error("_on_tick(draw_static_boundaries)", exc)
            
            # Schedule next tick
            self._schedule_tick()
        except Exception as e:
            self._logger.log_error("_on_tick", e)
    
    # ==================== UTILITY ====================
    
    def _clear_all_leds(self):
        """Clear all LEDs on the grid."""
        try:
            if self._active_sequencer:
                self._active_sequencer._clear_all_leds(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_clear_all_leds", e)
    
    def _refresh_grid(self):
        """Refresh the grid display."""
        try:
            if self._active_sequencer:
                self._active_sequencer.refresh_grid(self._matrix_rows_raw)
        except Exception as e:
            self._logger.log_error("_refresh_grid", e)
    
    def _blink_button(self, button, count):
        """Blink a button a specified number of times."""
        # This would be implemented with a task scheduler
        pass
