import sys

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import MenuNavigator, make_button_column

# TODO: Background image


class MainMenuState(BaseState):
    """
    Top-level menu state shown at application start.

    Presents three buttons — *Play*, *Settings*, and *Quit Game* — and
    delegates navigation to the state manager.
    """

    def enter(self):
        """
        Create and display the three main menu buttons.
        """
        self.buttons = make_button_column(
            self.app,
            [
                ("Play", self.choose_level),
                ("Settings", self.enter_settings),
                ("Quit Game", self.quit_game),
            ],
            top_z=0.3,
            step=0.3,
        )
        self.play_button, self.settings_button, self.quit_button = self.buttons
        self.menu_navigator = MenuNavigator(
            self.app,
            [[self.play_button], [self.settings_button], [self.quit_button]],
        )

    def choose_level(self):
        """
        Navigate to the level selection screen.
        """
        self.app.state_manager.pop()
        self.app.state_manager.push(self.app.state_manager.LEVEL_SELECTION_MENU_STATE)

    def enter_settings(self):
        """
        Navigate to the settings hub.
        """
        self.app.state_manager.push(self.app.state_manager.SETTINGS_STATE)

    def pause(self):
        for button in self.buttons:
            button.hide()

    def resume(self):
        for button in self.buttons:
            button.show()

    def quit_game(self):
        """
        Exit the process immediately.
        """
        sys.exit()

    def exit(self):
        """
        Destroy all menu buttons and force a frame render.
        """
        self.menu_navigator.remove()
        for button in self.buttons:
            button.destroy()
        self.force_render()
