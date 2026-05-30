import sys

from direct.gui.DirectGui import DirectFrame, DirectLabel

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton

# TODO: Overlay transparent-grey image between game and menu buttons
# TODO: Stats of the level


class DeathMenuState(BaseState):
    def enter(self):
        self.frame = DirectFrame(
            frameSize=(self.app.a2dLeft + 0.5, self.app.a2dRight - 0.5, -0.8, 0.8),
            frameColor=(0, 0, 0, 0.6),
            pos=(0, 0, 0),
        )
        self.frame.setTransparency(True)
        self.text_label = DirectLabel(
            text="You died",
            scale=0.1,
            pos=(0.0, 0.0, 0.3),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
        )
        button_scale = 0.5
        text_scale = 0.15
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

    def return_to_main(self):
        self.app.state_manager.clear()
        self.app.state_manager.replace(self.app.state_manager.MAIN_MENU_STATE)

    def quit_game(self):
        sys.exit()

    def exit(self):
        self.text_label.destroy()
        self.return_button.destroy()
        self.quit_button.destroy()
        self.frame.destroy()
