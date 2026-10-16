"""
Settings hub menu — a small landing screen that routes to the individual
settings screens (gameplay, input bindings, graphics).

Reached from the main menu and the pause menu via their *Settings* button.
"""

from direct.gui.DirectGui import DirectFrame

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import MenuNavigator, make_button_column


class SettingsMenuState(BaseState):
    """
    Landing screen presenting one button per settings category plus *Back*.
    """

    def enter(self):
        """Create and display the settings-category buttons."""
        # All-black background: hides the paused flight when opened from the
        # pause menu, looking the same as when opened from the main menu
        self.bg = DirectFrame(
            frameSize=(self.app.a2dLeft, self.app.a2dRight, -1.0, 1.0),
            frameColor=(0, 0, 0, 1),
        )
        self.buttons = make_button_column(
            self.app,
            [
                ("Gameplay Settings", self.enter_gameplay_settings),
                ("Input Settings", self.enter_input_settings),
                ("Graphics Settings", self.enter_graphics_settings),
                ("Back", self.back),
            ],
            top_z=0.45,
            step=0.3,
        )
        (
            self.gameplay_button,
            self.input_button,
            self.graphics_button,
            self.back_button,
        ) = self.buttons
        self.menu_navigator = MenuNavigator(
            self.app,
            [
                [self.gameplay_button],
                [self.input_button],
                [self.graphics_button],
                [self.back_button],
            ],
            on_back=self.back,
        )

    def enter_gameplay_settings(self):
        """Navigate to the gameplay settings screen."""
        self.app.state_manager.push(self.app.state_manager.GAMEPLAY_SETTINGS_STATE)

    def enter_input_settings(self):
        """Navigate to the input settings screen."""
        self.app.state_manager.push(self.app.state_manager.INPUT_SETTINGS_STATE)

    def enter_graphics_settings(self):
        """Navigate to the graphics settings screen."""
        self.app.state_manager.push(self.app.state_manager.GRAPHICS_SETTINGS_STATE)

    def back(self):
        """Return to the menu that opened the settings hub."""
        self.app.state_manager.pop()

    def pause(self):
        """Hide the buttons while a settings screen is open on top."""
        for button in self.buttons:
            button.hide()

    def resume(self):
        """Re-show the buttons when a settings screen above is popped."""
        for button in self.buttons:
            button.show()

    def exit(self):
        """Destroy all buttons and force a frame render."""
        self.menu_navigator.remove()
        for button in self.buttons:
            button.destroy()
        self.bg.destroy()
        self.force_render()
