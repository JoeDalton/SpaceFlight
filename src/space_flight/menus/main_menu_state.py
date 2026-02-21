import sys

from direct.gui.DirectGui import DirectButton

from space_flight.game.game_state import GameState
from space_flight.global_architecture.base_state import BaseState


class MainMenuState(BaseState):
    def enter(self):
        self.start_button = DirectButton(
            text="Start Game",
            scale=0.1,
            command=self.start_game,
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

    def start_game(self):
        self.app.state_manager.change_state(GameState)

    def enter_settings(self):
        pass

    def quit_game(self):
        sys.exit()

    def exit(self):
        self.start_button.destroy()
        self.settings_button.destroy()
        self.quit_button.destroy()
        self.force_render()
