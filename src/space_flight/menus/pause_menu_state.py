from direct.gui.DirectGui import DirectFrame

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import (
    MenuNavigator,
    make_button_column,
    quit_game,
    return_to_main_menu,
)


class PauseMenuState(BaseState):
    """
    In-game pause menu.  Its menu navigator blocks the flight inputs below it,
    and going back (including with the pause key) resumes the game.
    """

    def enter(self):
        self.frame = DirectFrame(
            frameSize=(self.app.a2dLeft + 0.5, self.app.a2dRight - 0.5, -0.8, 0.8),
            frameColor=(0, 0, 0, 0.6),
            pos=(0, 0, 0),
        )
        self.frame.setTransparency(True)
        self.buttons = make_button_column(
            self.app,
            [
                ("Resume Game", self.resume_game),
                ("Settings", self.enter_settings),
                ("Return to main menu", self.return_to_main),
                ("Quit Game", self.quit_game),
            ],
            top_z=0.45,
            step=0.3,
        )
        (
            self.resume_button,
            self.settings_button,
            self.return_button,
            self.quit_button,
        ) = self.buttons
        self.menu_navigator = MenuNavigator(
            self.app,
            [
                [self.resume_button],
                [self.settings_button],
                [self.return_button],
                [self.quit_button],
            ],
            on_back=self.resume_game,
        )

    def resume_game(self):
        self.app.state_manager.pop()

    def enter_settings(self):
        self.app.state_manager.push(self.app.state_manager.SETTINGS_STATE)

    def pause(self):
        for button in self.buttons:
            button.hide()
        self.frame.hide()

    def resume(self):
        self.frame.show()
        for button in self.buttons:
            button.show()

    def return_to_main(self):
        return_to_main_menu(self.app)

    def quit_game(self):
        quit_game(self.app)

    def exit(self):
        self.menu_navigator.remove()
        for button in self.buttons:
            button.destroy()
        self.frame.destroy()
