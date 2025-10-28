from __future__ import absolute_import, print_function, unicode_literals
import os
from datetime import datetime
import re


def _extract_version_tuple(name):
    match = re.search(r"(\d+(?:\.\d+)*)", name)
    if not match:
        return ()
    parts = [int(x) for x in match.group(1).split('.') if x.isdigit()]
    padding = [0] * max(0, 3 - len(parts))
    return tuple(parts + padding)

class SequencerLogger(object):
    """
    Granular logging system for Step Sequencer debugging.
    Logs to Sequencer_Debugger.txt with category-based filtering.
    """
    
    # LOGGING CATEGORIES - Enable/disable specific areas independently
    CATEGORIES = {
        'GENERAL': True,                # General/uncategorized messages
        'INSTRUMENT_DETECTION': True,   # Device detection and classification
        'AUDIO_SAMPLE': True,           # Audio sample detection and manipulation
        'GRID_REFRESH': True,           # Grid rendering and note display
        'NOTE_OPERATIONS': True,        # Add/remove/modify notes
        'NOTE_LENGTH': True,            # Note length changes
        'LOOP_LENGTH': True,            # Loop length changes
        'NAVIGATION': False,            # Up/Down/Left/Right movements
        'CLIP_OPERATIONS': False,       # Clip slot access and manipulation
        'SCALE_DETECTION': False,       # Scale/key detection and changes
        'BUTTON_PRESS': True,           # Raw button press events
        'TIMING': False,                # Tempo, ticks, playhead updates
        'PLAYHEAD': False,              # Playhead tracking
        'FUNCTIONS': True,              # Copy/paste/clear/fill functions
        'ENTRY_EXIT': True,             # Sequencer mode enter/exit
        'ERRORS': True,                 # All errors and exceptions
        'PERFORMANCE': False,           # Performance metrics
    }
    
    def __init__(self, log_file_path=None):
        """
        Initialize logger with optional custom log file path.
        Defaults to Ableton preferences folder.
        """
        if log_file_path:
            self._log_file = log_file_path
        else:
            # Try to find Ableton preferences folder
            appdata = os.environ.get('APPDATA', '')
            ableton_base = os.path.join(appdata, 'Ableton')
            log_file = None
            
            # Search for Live folders (e.g., "Live 12.2.5", "Live 11.3.4")
            if os.path.exists(ableton_base):
                try:
                    live_folders = [f for f in os.listdir(ableton_base) if f.startswith('Live ') and os.path.isdir(os.path.join(ableton_base, f))]
                    if live_folders:
                        live_12 = [f for f in live_folders if f.startswith('Live 12')]
                        candidates = live_12 if live_12 else live_folders
                        candidates.sort(key=_extract_version_tuple, reverse=True)
                        prefs_path = os.path.join(ableton_base, candidates[0], 'Preferences')
                        if os.path.exists(prefs_path):
                            log_file = os.path.join(prefs_path, 'Sequencer_Debugger.txt')
                except Exception:
                    pass
            
            # Fallback to temp folder if Ableton folder not found
            if not log_file:
                temp_dir = os.environ.get('TEMP', os.environ.get('TMP', 'C:\\Temp'))
                log_file = os.path.join(temp_dir, 'Sequencer_Debugger.txt')
            
            self._log_file = log_file
        
        self._enabled = True
        self._control_surface = None
        
        # Write header on init
        self._write_header()
    
    def set_control_surface(self, control_surface):
        """Set control surface reference for fallback logging to Ableton log"""
        self._control_surface = control_surface
    
    def _write_header(self):
        """Write session header to log file"""
        try:
            with open(self._log_file, 'a') as f:
                f.write("\n" + "="*80 + "\n")
                f.write("STEP SEQUENCER DEBUG SESSION - %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                f.write("="*80 + "\n")
                f.write("ENABLED CATEGORIES: %s\n" % ', '.join([k for k, v in self.CATEGORIES.items() if v]))
                f.write("="*80 + "\n\n")
        except Exception:
            pass
    
    def log(self, category, message):
        """
        Log a message if the category is enabled.
        
        Args:
            category (str): One of CATEGORIES keys
            message (str): Message to log
        """
        if not self._enabled:
            return
        
        # Always log errors regardless of category setting
        if category == 'ERRORS':
            force_log = True
        else:
            force_log = False
        
        # Check if category is enabled
        if not force_log and (category not in self.CATEGORIES or not self.CATEGORIES[category]):
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
        formatted_message = "[%s] [%s] %s" % (timestamp, category, message)
        
        # Write to file
        try:
            with open(self._log_file, 'a') as f:
                f.write(formatted_message + "\n")
        except Exception as e:
            # Fallback to Ableton log if file write fails
            if self._control_surface:
                try:
                    self._control_surface.log_message("LOGGER ERROR: " + str(e))
                except Exception:
                    pass
        
        # Also write to Ableton log for errors
        if category == 'ERRORS' and self._control_surface:
            try:
                self._control_surface.log_message(formatted_message)
            except Exception:
                pass
    
    def separator(self, title=None):
        """Write a visual separator to the log"""
        if not self._enabled:
            return
        
        try:
            with open(self._log_file, 'a') as f:
                f.write("\n" + "-"*80 + "\n")
                if title:
                    f.write("  %s\n" % title)
                    f.write("-"*80 + "\n")
        except Exception:
            pass
    
    def enable_category(self, category):
        """Enable logging for a specific category"""
        if category in self.CATEGORIES:
            self.CATEGORIES[category] = True
            self.log('ENTRY_EXIT', "Enabled logging category: %s" % category)
    
    def disable_category(self, category):
        """Disable logging for a specific category"""
        if category in self.CATEGORIES:
            self.CATEGORIES[category] = False
            self.log('ENTRY_EXIT', "Disabled logging category: %s" % category)
    
    def enable_all(self):
        """Enable all logging categories"""
        for category in self.CATEGORIES:
            self.CATEGORIES[category] = True
        self.log('ENTRY_EXIT', "Enabled ALL logging categories")
    
    def disable_all(self):
        """Disable all logging categories (except ERRORS)"""
        for category in self.CATEGORIES:
            if category != 'ERRORS':
                self.CATEGORIES[category] = False
        self.log('ENTRY_EXIT', "Disabled all logging categories except ERRORS")
    
    def clear_log(self):
        """Clear the log file"""
        try:
            with open(self._log_file, 'w') as f:
                f.write("")
            self._write_header()
        except Exception:
            pass
    
    def get_log_path(self):
        """Return the full path to the log file"""
        return self._log_file
    
    def log_error(self, context, exception):
        """
        Log an error with exception details.
        
        Args:
            context (str): Context where error occurred (e.g., function name)
            exception (Exception): The exception object
        """
        error_msg = "%s: %s" % (context, str(exception))
        self.log('ERRORS', error_msg)
    
    def log_info(self, message):
        """
        Log a general info message.
        
        Args:
            message (str): Message to log
        """
        self.log('GENERAL', message)
