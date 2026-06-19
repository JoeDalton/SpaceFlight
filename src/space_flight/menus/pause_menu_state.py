import sys

from direct.gui.DirectGui import DirectFrame

from space_flight import RECORD_GAME
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton
from space_flight.ui.input_context import PauseMenuInputContext


class PauseMenuState(BaseState):
    def enter(self):
        self.app.input_context_stack.push(PauseMenuInputContext(app=self.app))
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
            pos=(0.0, 0.0, 0.45),
            layout="center",
        )
        self.settings_button = CustomButton(
            app=self.app,
            text="Input Settings",
            scale=button_scale,
            text_scale=text_scale,
            command=self.enter_settings,
            pos=(0.0, 0.0, 0.15),
            layout="center",
        )
        self.return_button = CustomButton(
            app=self.app,
            text="Return to main menu",
            scale=button_scale,
            text_scale=text_scale,
            command=self.return_to_main,
            pos=(0.0, 0.0, -0.15),
            layout="center",
        )
        self.quit_button = CustomButton(
            app=self.app,
            text="Quit Game",
            scale=button_scale,
            text_scale=text_scale,
            command=self.quit_game,
            pos=(0.0, 0.0, -0.45),
            layout="center",
        )

    def resume_game(self):
        self.app.state_manager.pop()

    def enter_settings(self):
        self.app.state_manager.push(self.app.state_manager.INPUT_SETTINGS_STATE)

    def pause(self):
        self.resume_button.hide()
        self.settings_button.hide()
        self.return_button.hide()
        self.quit_button.hide()
        self.frame.hide()

    def resume(self):
        self.frame.show()
        self.resume_button.show()
        self.settings_button.show()
        self.return_button.show()
        self.quit_button.show()

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
        self.settings_button.destroy()
        self.return_button.destroy()
        self.quit_button.destroy()
        self.frame.destroy()
        self.app.input_context_stack.pop()
