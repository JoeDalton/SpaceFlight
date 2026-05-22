from direct.gui.DirectGui import DirectFrame, DirectLabel, DirectScrolledFrame
from panda3d.core import TextNode

from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton

# TODO: Background image


class LevelSelectionMenuState(BaseState):
    LEVELS = [
        {
            "name": "Dev",
            "description": "A development level that usually "
            "demonstrates the latest implemented features",
        },
        {"name": "Intro", "description": "The first `game ready` level."},
    ]

    def enter(self):
        """
        Build the level selection menu
        """

        main_button_scale = 0.3
        self.title_text_scale = 0.1
        # State change buttons
        self.back_button = CustomButton(
            app=self.app,
            pos=(0.5, 0.0, -0.9),
            command=self.back,
            text="Back",
            scale=main_button_scale,
            layout="center",
        )

        self.start_button = CustomButton(
            app=self.app,
            pos=(1.2, 0.0, -0.9),
            command=self.start_game,
            text="Start Game",
            scale=main_button_scale,
            layout="center",
        )
        self.start_button.hide()

        self.description_frame = DirectFrame(
            frameSize=(0.0, self.app.a2dRight - 0.1, 0.3, 1.55),
            frameColor=(0.25, 0.25, 0.25, 0.3),
            pos=(0, 0, -0.8),
            text="",
            text_wordwrap=30,
            text_align=TextNode.ALeft,
            text_scale=0.05,
            text_fg=(1, 1, 1, 1),
            text_pos=(0.05, 1.45),
            text_shadow=(0, 0, 0, 0.35),
            text_shadowOffset=(-0.05, -0.05),
        )
        self.description_frame.setTransparency(True)

        self.create_level_list()

    def start_game(self):
        level_names = []
        for level in self.LEVELS:
            level_names.append(level["name"])
        if self.app.configuration.get("selected_level") in level_names:
            self.app.state_manager.replace(self.app.state_manager.GAME_STATE)

    def back(self):
        self.app.state_manager.pop()
        self.app.state_manager.push(self.app.state_manager.MAIN_MENU_STATE)

    def exit(self):
        self.back_button.destroy()
        self.start_button.destroy()
        self.lstActionMap.destroy()
        self.title.destroy()
        self.description_frame.destroy()

        self.force_render()

    def create_level_list(self):
        """
        Creates a list of levels for the user to select
        """
        # create a sample title
        self.title = DirectLabel(
            scale=self.title_text_scale,
            pos=(
                self.app.a2dLeft + 0.05,
                0.0,
                self.app.a2dTop - (self.title_text_scale + 0.05),
            ),
            frameColor=(0, 0, 0, 0),
            text="Level selection",
            text_align=TextNode.ALeft,
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
        )
        self.title.setTransparency(1)

        # Change the default dialog skin.
        self.level_buttons = []

        # create the scrolled frame that will hold our list
        self.lstActionMap = DirectScrolledFrame(
            frameSize=(self.app.a2dLeft, -0.25, 0.0, 1.55),
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, -0.8),
            verticalScroll_scrollSize=0.2,
            verticalScroll_frameColor=(0.02, 0.02, 0.02, 1),
            verticalScroll_thumb_relief=1,
            verticalScroll_thumb_geom=self.app.menu_models.thumb_geom,
            verticalScroll_thumb_pressEffect=False,
            verticalScroll_thumb_frameColor=(0, 0, 0, 0),
            verticalScroll_incButton_relief=1,
            verticalScroll_incButton_geom=self.app.menu_models.inc_geom,
            verticalScroll_incButton_pressEffect=False,
            verticalScroll_incButton_frameColor=(0, 0, 0, 0),
            verticalScroll_decButton_relief=1,
            verticalScroll_decButton_geom=self.app.menu_models.dec_geom,
            verticalScroll_decButton_pressEffect=False,
            verticalScroll_decButton_frameColor=(0, 0, 0, 0),
        )

        self.actionLabels = {}
        for idx, level in enumerate(self.LEVELS):
            level_name = level["name"]
            item = self.__makeListItem(level_name, idx)
            item.reparentTo(self.lstActionMap.getCanvas())

        # Recalculate the canvas size to set scrollbars if necesary
        self.lstActionMap["canvasSize"] = (
            self.app.a2dLeft + 0.05,
            -0.3,
            -(len(self.LEVELS) * 0.1),
            0.09,
        )
        self.lstActionMap.setCanvasSize()

    def __makeListItem(self, level_name, index):
        item = DirectFrame(
            text="",
            geom=None,
            geom_scale=(self.app.a2dRight - 0.05, 1, 0.1),
            frameSize=(self.app.a2dLeft + 0.05, self.app.a2dRight - 0.05, -0.05, 0.05),
            frameColor=(1, 0, 0, 0),
            text_align=TextNode.ALeft,
            text_scale=0.05,
            text_fg=(1, 1, 1, 1),
            text_pos=(self.app.a2dLeft + 0.3, -0.015),
            text_shadow=(0, 0, 0, 0.35),
            text_shadowOffset=(-0.05, -0.05),
            pos=(0.05, 0, -(0.10 * index)),
        )
        item.setTransparency(True)

        buttonScale = 0.2
        btn = CustomButton(
            app=self.app,
            pos=(self.app.a2dLeft + (0.898 * buttonScale + 0.3), 0, 0),
            command=self.set_level,
            text=level_name,
            scale=buttonScale,
            extraArgs=[index],
            parent=item,
        )
        self.level_buttons.append(btn)
        return item

    def set_level(self, button_index: int):
        level_name = self.LEVELS[button_index]["name"]
        for idx, btn in enumerate(self.level_buttons):
            if idx == button_index:
                if self.app.configuration.get("selected_level") == level_name:
                    # Unselect current level and reset the button
                    self.app.configuration["selected_level"] = None
                    self.description_frame["text"] = ""
                    btn.reset()
                    self.start_button.hide()
                else:
                    # Set the level and make the button "PRESSED"
                    self.app.configuration["selected_level"] = level_name
                    self.description_frame["text"] = self.LEVELS[button_index][
                        "description"
                    ]
                    btn.set_pressed()
                    self.start_button.show()
            else:
                # Reet all other level buttons
                btn.reset()
