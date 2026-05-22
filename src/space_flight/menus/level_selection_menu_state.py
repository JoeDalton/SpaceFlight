from direct.gui.DirectGui import (
    DGG,
    DirectButton,
    DirectFrame,
    DirectLabel,
    DirectScrolledFrame,
)
from panda3d.core import TextNode, VBase4, Vec2

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.base_state import BaseState

# TODO: Background image


class LevelSelectionMenuState(BaseState):
    LEVELS = [
        {
            "name": "Dev",
            "description": "A development level that usually "
            "demonstrates the latest implemented features",
        },
        {"name": "Intro", "description": "The first `game ready` level."},
    ] + [{"name": "toto", "description": "Lorem ipsum"}] * 20

    def enter(self):
        """
        Build the level selection menu
        """
        button_maps = self.app.asset_manager.get_asset(
            asset_type="model",
            path=DATAFILES_PATH / "menus" / "button_map.egg",
        )

        self.buttonGeom = (
            button_maps.find("**/ready"),
            button_maps.find("**/click"),
            button_maps.find("**/hover"),
            button_maps.find("**/disabled"),
        )

        main_button_scale = 0.3
        self.title_text_scale = 0.1
        # State change buttons
        self.back_button = DirectButton(
            text="Back",
            image=self.buttonGeom,
            scale=main_button_scale,
            command=self.back,
            pos=(0.5, 0.0, -0.9),
            text_scale=0.25,
            text_align=TextNode.ALeft,
            text_fg=VBase4(1, 1, 1, 1),
            text_pos=Vec2(-0.9, -0.085),
            relief=1,
            pad=Vec2(0.01, 0.01),
            frameColor=VBase4(0, 0, 0, 0),
            frameSize=VBase4(-1.0, 1.0, -0.25, 0.25),
            pressEffect=True,
        )
        self.start_button = DirectButton(
            text="Start Game",
            image=self.buttonGeom,
            scale=main_button_scale,
            command=self.start_game,
            pos=(1.2, 0.0, -0.9),
            text_scale=0.25,
            text_align=TextNode.ALeft,
            text_fg=VBase4(1, 1, 1, 1),
            text_pos=Vec2(-0.9, -0.085),
            relief=1,
            pad=Vec2(0.01, 0.01),
            frameColor=VBase4(0, 0, 0, 0),
            frameSize=VBase4(-1.0, 1.0, -0.25, 0.25),
            pressEffect=True,
        )
        self.start_button.hide()

        self.description_frame = DirectFrame(
            frameSize=VBase4(0.0, self.app.a2dRight - 0.1, 0.3, 1.55),
            frameColor=VBase4(0.25, 0.25, 0.25, 0.3),
            pos=(0, 0, -0.8),
            text="",
            text_wordwrap=30,
            text_align=TextNode.ALeft,
            text_scale=0.05,
            text_fg=VBase4(1, 1, 1, 1),
            text_pos=(0.05, 1.45),
            text_shadow=VBase4(0, 0, 0, 0.35),
            text_shadowOffset=Vec2(-0.05, -0.05),
        )
        self.description_frame.setTransparency(True)

        self.create_level_list()

    def start_game(self):
        if self.app.configuration.get("selected_level") in self.LEVELS:
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
            frameColor=VBase4(0, 0, 0, 0),
            text="Level selection",
            text_align=TextNode.ALeft,
            text_fg=VBase4(1, 1, 1, 1),
            text_shadow=VBase4(0, 0, 0, 0.75),
            text_shadowOffset=Vec2(0.05, 0.05),
        )
        self.title.setTransparency(1)

        # Change the default dialog skin.
        self.level_buttons = []
        # DGG.setDefaultDialogGeom(DATAFILES_PATH / "menus" / "dialog.png")
        DGG.setDefaultDialogGeom(
            self.app.asset_manager.get_asset(
                asset_type="texture",
                path=DATAFILES_PATH / "menus" / "dialog.png",
            )
        )

        # Set up the list of actions that we can map keys to
        # create a frame that will create the scrollbars for us
        # Load the models for the scrollbar elements
        thumb_map = self.app.asset_manager.get_asset(
            asset_type="model",
            path=DATAFILES_PATH / "menus" / "thumb_map.egg",
        )
        thumb_geom = (
            thumb_map.find("**/thumb_ready"),
            thumb_map.find("**/thumb_click"),
            thumb_map.find("**/thumb_hover"),
            thumb_map.find("**/thumb_disabled"),
        )
        inc_map = self.app.asset_manager.get_asset(
            asset_type="model",
            path=DATAFILES_PATH / "menus" / "inc_map.egg",
        )
        inc_geom = (
            inc_map.find("**/inc_ready"),
            inc_map.find("**/inc_click"),
            inc_map.find("**/inc_hover"),
            inc_map.find("**/inc_disabled"),
        )
        dec_map = self.app.asset_manager.get_asset(
            asset_type="model",
            path=DATAFILES_PATH / "menus" / "dec_map.egg",
        )
        dec_geom = (
            dec_map.find("**/dec_ready"),
            dec_map.find("**/dec_click"),
            dec_map.find("**/dec_hover"),
            dec_map.find("**/dec_disabled"),
        )

        # create the scrolled frame that will hold our list
        self.lstActionMap = DirectScrolledFrame(
            # make the frame occupy the whole window
            # frameSize=VBase4(self.app.a2dLeft, self.app.a2dRight, 0.0, 1.55),
            frameSize=VBase4(self.app.a2dLeft, -0.25, 0.0, 1.55),
            # set the frames color to white
            # frameColor=VBase4(0, 0, 0.25, 0.75),
            frameColor=VBase4(0, 0, 0, 0),
            pos=(0, 0, -0.8),
            verticalScroll_scrollSize=0.2,
            verticalScroll_frameColor=VBase4(0.02, 0.02, 0.02, 1),
            verticalScroll_thumb_relief=1,
            verticalScroll_thumb_geom=thumb_geom,
            verticalScroll_thumb_pressEffect=False,
            verticalScroll_thumb_frameColor=VBase4(0, 0, 0, 0),
            verticalScroll_incButton_relief=1,
            verticalScroll_incButton_geom=inc_geom,
            verticalScroll_incButton_pressEffect=False,
            verticalScroll_incButton_frameColor=VBase4(0, 0, 0, 0),
            verticalScroll_decButton_relief=1,
            verticalScroll_decButton_geom=dec_geom,
            verticalScroll_decButton_pressEffect=False,
            verticalScroll_decButton_frameColor=VBase4(0, 0, 0, 0),
        )

        # Create the list items
        self.listBGEven = self.app.loader.loadModel(
            DATAFILES_PATH / "menus" / "list_item_even"
        )
        self.listBGOdd = self.app.loader.loadModel(
            DATAFILES_PATH / "menus" / "list_item_odd"
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
        def set_level(button_index: int):
            level_name = self.LEVELS[button_index]["name"]
            for idx, btn in enumerate(self.level_buttons):
                if idx == button_index:
                    if self.app.configuration.get("selected_level") == level_name:
                        # Unselect current level and make the button "READY"
                        self.app.configuration["selected_level"] = None
                        self.description_frame["text"] = ""
                        btn["geom"] = self.buttonGeom[0]
                        self.start_button.hide()
                    else:
                        # Set the level and make the button "PRESSED"
                        self.app.configuration["selected_level"] = level_name
                        self.description_frame["text"] = self.LEVELS[button_index][
                            "description"
                        ]
                        btn["geom"] = self.buttonGeom[1]
                        self.start_button.show()
                else:
                    # Set all other level buttons to "READY"
                    btn["geom"] = self.buttonGeom[0]

        # if index % 2 == 0:
        #     bg = self.listBGEven
        # else:
        #     bg = self.listBGOdd
        item = DirectFrame(
            text="",
            geom=None,
            # geom=bg,
            geom_scale=(self.app.a2dRight - 0.05, 1, 0.1),
            frameSize=VBase4(
                self.app.a2dLeft + 0.05, self.app.a2dRight - 0.05, -0.05, 0.05
            ),
            frameColor=VBase4(1, 0, 0, 0),
            text_align=TextNode.ALeft,
            text_scale=0.05,
            text_fg=VBase4(1, 1, 1, 1),
            text_pos=(self.app.a2dLeft + 0.3, -0.015),
            text_shadow=VBase4(0, 0, 0, 0.35),
            text_shadowOffset=Vec2(-0.05, -0.05),
            pos=(0.05, 0, -(0.10 * index)),
        )
        item.setTransparency(True)

        buttonScale = 0.2
        btn = DirectButton(
            text=level_name,
            geom=self.buttonGeom,
            scale=buttonScale,
            text_scale=0.25,
            text_align=TextNode.ALeft,
            text_fg=VBase4(1, 1, 1, 1),
            text_pos=Vec2(-0.9, -0.085),
            relief=1,
            pad=Vec2(0.01, 0.01),
            frameColor=VBase4(0, 0, 0, 0),
            frameSize=VBase4(-1.0, 1.0, -0.25, 0.25),
            pos=(self.app.a2dLeft + (0.898 * buttonScale + 0.3), 0, 0),
            pressEffect=True,
            command=set_level,
            extraArgs=[index],
        )
        btn.setTransparency(True)
        btn.reparentTo(item)
        self.level_buttons.append(btn)
        return item
