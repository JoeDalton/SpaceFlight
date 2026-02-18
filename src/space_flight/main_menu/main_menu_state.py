# from direct.gui.DirectGui import DirectButton

from space_flight.game.game_state import GameState
from space_flight.global_architecture.base_state import BaseState


class MainMenuState(BaseState):
    def enter(self):
        # DEBUG
        self.start_game()
        # self.button = DirectButton(
        #     text="Start Game",
        #     scale=0.1,
        #     command=self.start_game
        # )

    def start_game(self):
        self.app.state_manager.change_state(GameState)

    def exit(self):
        pass
        # self.button.destroy()
