import sys

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton

# TODO: Background image


class MainMenuState(BaseState):
    def enter(self):
        button_scale = 0.5
        text_scale = 0.15
        self.play_button = CustomButton(
            app=self.app,
            text="Play",
            scale=button_scale,
            text_scale=text_scale,
            command=self.choose_level,
            pos=(0.0, 0.0, 0.3),
            layout="center",
        )
        self.settings_button = CustomButton(
            app=self.app,
            text="Settings",
            scale=button_scale,
            text_scale=text_scale,
            command=self.enter_settings,
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
