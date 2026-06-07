import sys

from direct.gui.DirectGui import DirectFrame

from space_flight import RECORD_GAME
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton
from space_flight.ui.input_context import PauseMenuInputContext


class PauseMenuState(BaseState):
    def enter(self):
        game_state = self.app.state_manager.stack[-2]
        self.app.input_context_stack.push(PauseMenuInputContext(game=game_state))
        self.frame = DirectFrame(
            frameSize=(self.app.a2dLeft + 0.5, self.app.a2dRight - 0.5, -0.8, 0.8),
            frameColor=(0, 0, 0, 0.6),
            pos=(0, 0, 0),
        )
        self.frame.setTransparency(True)
        button_scale = 0.5
        text_scale = 0.15
        self.resume_button = CustomButton(
            app=self.app,
            text="Resume Game",
            scale=button_scale,
            text_scale=text_scale,
            command=self.resume_game,
            pos=(0.0, 0.0, 0.3),
            layout="center",
        )
        self.return_button = CustomButton(
            app=self.app,
            text="Return to main menu",
            scale=button_scale,
            text_scale=text_scale,
            command=self.return_to_main,
            pos=(0.0, 0.0, 0.0),
            layout="center",
        )
        self.quit_button = CustomButton(
            app=self.app,
            text="Quit Game",
            scale=button_scale,
            text_scale=text_scale,
            command=self.quit_game,
            pos=(0.0, 0.0, -0.3),
            layout="center",
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
        self.app.input_context_stack.pop()
