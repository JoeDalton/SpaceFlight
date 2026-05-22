import sys

from direct.gui.DirectGui import DirectButton, DirectFrame

from space_flight import RECORD_GAME
from space_flight.global_architecture.base_state import BaseState

# TODO: overlay transparent-grey image between game and  menu buttons


class PauseMenuState(BaseState):
    def enter(self):
        self.frame = DirectFrame(
            frameSize=(self.app.a2dLeft + 0.5, self.app.a2dRight - 0.5, -0.8, 0.8),
            frameColor=(0, 0, 0, 0.6),
            pos=(0, 0, 0),
        )
        self.frame.setTransparency(True)
        self.resume_button = DirectButton(
            text="Resume Game",
            scale=0.1,
            command=self.resume_game,
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

    def resume_game(self):
        self.app.state_manager.pop()

    def return_to_main(self):
        self.app.state_manager.clear()
        self.app.state_manager.replace(self.app.state_manager.MAIN_MENU_STATE)

    def quit_game(self):
        if RECORD_GAME:
            # Record game logs
            self.app.state_manager.stack[-2].record.save()
        sys.exit()

    def exit(self):
        self.resume_button.destroy()
        self.return_button.destroy()
        self.quit_button.destroy()
        self.frame.destroy()
