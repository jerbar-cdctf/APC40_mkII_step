---
trigger: always_on
---

Always use Live 12 API 
Always double check the AKAI APC40MK2_Communications_Protocol_v1.2
Always check the latest ableton log at C:\Users\Jeremy\AppData\Roaming\Ableton\Live 12.2.5\Preferences\Log.txt
Know that I have a powershell script that will flush the Ableton programdata location for the controller, including the pycache folder, and copy the latest version in. The script also clears the log out so it stays fresh.
We created some debugging and logging module, when creating new functions or features, always add logging and update the logging guide, then enable the logs in the debugger and log settings.

We can if needed, use AbletonOSC to send commands into Ableton. I'm not 100% for sure if its needed or not.


I'll try to also describe the overall goal of what we are trying to acomplish. (Some of these may already be done)
Utilizing the AKAI APC40 mkII controller,
Adding functionality of a Step Sequencer via the User button.
This should take complete control over the entire controller.
The only thing that should always remain the same is the PAN, SENDS, USER, PLAY, RECORD, SESSION, METRONOME, TAP TEMPO and the TEMPO knob. These should essentially be global functions and shoudl remain that way in the step sequencer.

The Matrix 8x5 grid consist of 40RGB buttons, which is what we'll use to place notes and remove notes.
To the Right of the 8x5 Matrix gird is the Scene launch buttons. there is 1 button per each row.
We will use this for custom functions. Pressing the button will cycle through what function is assigned to the drum on that row currently. It should also have a no function option that leaves the LED off.

On the bottom of the 8x5 grid are a 9x2 grid that is oragne leds only.
the top row is refered to stop clip, and the 2nd row is the track selection buttons.
The last column is the stop all clips on the top row, and the master button on the bottom row.

The stop all clips button should roate the active function that master button when pressed executes.
When the stop all clips button is pressed, it should stay on (orange) while it blinks the scene launch buttons the color of the function (this is only a visual indication of what function is currently selected for execution. It should not modify any of the drums currently selected function). once blinking stops, the stop all clips button should turn its orange light off.
once a function is executed, the function should clear its selected drums, the stop all clips should return to no function selected.
The Master button when execution works, should blink 3 times, when it fails due to no drums for that function selected, it should blink 5 times.

Function Colors & Actions
RED = Clear notes
YELLOW = Copy notes
ORANGE = Paste notes
BLUE = MPE Marker (visual indicator, no action on execute, we are not yet to the MPE function debugging it may be used then)
PURPLE = Fill with quarter notes
DARK_PURPLE = Fill with eighth notes
BROWN = Fill with sixteenth notes
DARK_BROWN = Fill with whole notes

Remind me from time to time to update the rules, especially if we need to help define guidelines, or goals of any functionality or feature.