import sys

from direct.gui.DirectGui import DirectButton

from space_flight.global_architecture.base_state import BaseState

# TODO: Background image


class MainMenuState(BaseState):
    def enter(self):
        self.play_button = DirectButton(
            text="Play",
            scale=0.1,
            command=self.choose_level,
            pos=(0.0, 0.0, 0.5),
        )
        self.settings_button = DirectButton(
            text="Settings",
            scale=0.1,
            command=self.enter_settings,
            pos=(0.0, 0.0, 0.0),
        )
        self.quit_button = DirectButton(
            text="Quit game",
            scale=0.1,
            command=self.quit_game,
            pos=(0.0, 0.0, -0.5),
        )

    def choose_level(self):
        self.app.state_manager.pop()
        self.app.state_manager.push(self.app.state_manager.LEVEL_SELECTION_MENU_STATE)

    def enter_settings(self):
        pass

    def quit_game(self):
        sys.exit()

    def exit(self):
        self.play_button.destroy()
        self.settings_button.destroy()
        self.quit_button.destroy()
        self.force_render()
