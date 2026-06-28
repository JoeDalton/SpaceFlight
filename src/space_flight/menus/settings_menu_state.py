"""
Settings hub menu — a small landing screen that routes to the individual
settings screens (input bindings, graphics).

Reached from the main menu and the pause menu via their *Settings* button.
"""

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton


class SettingsMenuState(BaseState):
    """
    Landing screen presenting one button per settings category plus *Back*.
    """

    def enter(self):
        """Create and display the settings-category buttons."""
        button_scale = 0.5
        text_scale = 0.15
        self.input_button = CustomButton(
            app=self.app,
            text="Input Settings",
            scale=button_scale,
            text_scale=text_scale,
            command=self.enter_input_settings,
            pos=(0.0, 0.0, 0.3),
            layout="center",
        )
        self.graphics_button = CustomButton(
            app=self.app,
            text="Graphics Settings",
            scale=button_scale,
            text_scale=text_scale,
            command=self.enter_graphics_settings,
            pos=(0.0, 0.0, 0.0),
            layout="center",
        )
        self.back_button = CustomButton(
            app=self.app,
            text="Back",
            scale=button_scale,
            text_scale=text_scale,
            command=self.back,
            pos=(0.0, 0.0, -0.3),
            layout="center",
        )

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
        self.input_button.hide()
        self.graphics_button.hide()
        self.back_button.hide()

    def resume(self):
        """Re-show the buttons when a settings screen above is popped."""
        self.input_button.show()
        self.graphics_button.show()
        self.back_button.show()

    def exit(self):
        """Destroy all buttons and force a frame render."""
        self.input_button.destroy()
        self.graphics_button.destroy()
        self.back_button.destroy()
        self.force_render()
