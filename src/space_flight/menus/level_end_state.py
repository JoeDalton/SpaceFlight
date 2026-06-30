"""
The terminal screen shown when a level ends, for any outcome (victory, defeat or
death).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from direct.gui.DirectGui import DirectFrame, DirectLabel

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton

if TYPE_CHECKING:
    from direct.showbase.ShowBase import ShowBase

# TODO: Overlay transparent-grey image between game and menu buttons
# TODO: Stats of the level

# Title shown for each level-ending outcome, plus a tint for the title text.
_OUTCOMES = {
    "victory": {"title": "Victory!", "color": (0.6, 1.0, 0.6, 1.0)},
    "defeat": {"title": "Defeat", "color": (1.0, 0.7, 0.4, 1.0)},
    "death": {"title": "You died", "color": (1.0, 0.5, 0.5, 1.0)},
}
_DEFAULT_COLOR = (1.0, 1.0, 1.0, 1.0)


class LevelEndState(BaseState):
    """
    Terminal screen shown when a level ends, for any outcome.

    The outcome (``victory``, ``defeat`` or ``death``) selects the title and its
    tint; an optional ``text`` gives the level-specific explanation beneath it.

    :param app: The ShowBase application
    :param outcome: One of ``victory``, ``defeat`` or ``death``
    :param text: Explanatory text shown beneath the title
    """

    def __init__(self, app: ShowBase, outcome: str = "victory", text: str = "") -> None:
        super().__init__(app)
        self.outcome = outcome
        self.text = text

    def enter(self) -> None:
        """
        Build the end-of-level overlay: title, explanation, and the menu buttons.
        """
        outcome = _OUTCOMES.get(self.outcome, {})
        title = outcome.get("title", self.outcome.capitalize())
        title_color = outcome.get("color", _DEFAULT_COLOR)

        self.frame = DirectFrame(
            frameSize=(self.app.a2dLeft + 0.5, self.app.a2dRight - 0.5, -0.8, 0.8),
            frameColor=(0, 0, 0, 0.6),
            pos=(0, 0, 0),
        )
        self.frame.setTransparency(True)
        self.text_label = DirectLabel(
            text=title,
            scale=0.12,
            pos=(0.0, 0.0, 0.4),
            frameColor=(0, 0, 0, 0),
            text_fg=title_color,
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
        )
        self.subtitle_label = DirectLabel(
            text=self.text,
            scale=0.06,
            pos=(0.0, 0.0, 0.2),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_wordwrap=20,
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
            pos=(0.0, 0.0, -0.1),
            layout="center",
        )
        self.quit_button = CustomButton(
            app=self.app,
            text="Quit Game",
            scale=button_scale,
            text_scale=text_scale,
            command=self.quit_game,
            pos=(0.0, 0.0, -0.4),
            layout="center",
        )

    def return_to_main(self) -> None:
        """
        Clear the state stack and return to the main menu.
        """
        self.app.state_manager.clear()
        self.app.state_manager.replace(self.app.state_manager.MAIN_MENU_STATE)

    def quit_game(self) -> None:
        """
        Quit the application.
        """
        sys.exit()

    def exit(self) -> None:
        """
        Destroy the overlay's widgets.
        """
        self.text_label.destroy()
        self.subtitle_label.destroy()
        self.return_button.destroy()
        self.quit_button.destroy()
        self.frame.destroy()
