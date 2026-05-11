import sys

from direct.gui.DirectGui import DirectButton, DirectLabel

from space_flight.global_architecture.base_state import BaseState

# TODO: Overlay transparent-grey image between game and menu buttons
# TODO: Stats of the level


class DeathMenuState(BaseState):
    def enter(self):
        self.text_label = DirectLabel(
            text="You died",
            scale=0.1,
            pos=(0.0, 0.0, 0.5),
        )
        self.return_button = DirectButton(
            text="Return to main menu",
            scale=0.1,
            command=self.return_to_main,
            pos=(0.0, 0.0, 0.0),
        )
        self.quit_button = DirectButton(
            text="Quit Game",
            scale=0.1,
            command=self.quit_game,
            pos=(0.0, 0.0, -0.5),
        )

    def return_to_main(self):
        self.app.state_manager.clear()
        self.app.state_manager.replace(self.app.state_manager.MAIN_MENU_STATE)

    def quit_game(self):
        sys.exit()

    def exit(self):
        self.text_label.destroy()
        self.return_button.destroy()
        self.quit_button.destroy()
