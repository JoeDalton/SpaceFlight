from time import sleep

from direct.gui.OnscreenImage import OnscreenImage
from direct.interval.IntervalGlobal import Sequence
from panda3d.core import TransparencyAttrib, WindowProperties

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.menu_utils import ProgressBar


class SplashState(BaseState):
    def enter(self):
        props = WindowProperties()
        props.setUndecorated(True)  # Removes window border & title bar
        props.setSize(1280, 544)  # Set splash size
        props.setTitle("Splash")  # Optional
        props.setOrigin(
            (self.app.pipe.getDisplayWidth() - 1280) // 2,
            (self.app.pipe.getDisplayHeight() - 544) // 2,
        )
        self.app.win.setClearColor((0, 0, 0, 0))

        self.app.win.requestProperties(props)

        tex = self.app.loader.loadTexture(
            DATAFILES_PATH / "sprites/splash_screen/splash.png"
        )
        self.splash = OnscreenImage(
            image=tex,
            scale=(1280 / 544, 1, 1),
            parent=self.app.aspect2d,
        )

        self.splash.setTransparency(TransparencyAttrib.MAlpha)
        self.splash.setColor(1, 1, 1, 1)

        # Render the splash bar to avoid texture stretching in two visible steps
        self.splash.hide()
        self.force_render()
        self.splash.show()
        blurbs = [
            "Mustering crews",
            "Setting hyperspace coordinates",
            "Loading proton torpedos",
            "Scanning derelict ship",
            "Fixing the Falcon's hyperdrive",
            "Calibrating laser cannons",
            "Clearing flight deck",
            "Scrambling interceptors",
            "Priming deflector shields",
            "Forming squadrons",
        ]

        self.progress_bar = ProgressBar(app=self.app, parent=self.splash, blurbs=blurbs)

        # Start loading assets
        self.app.asset_manager.load_game_assets(app_state=self)

    def on_loading_finished(self):
        self.sequence = Sequence(self.splash.colorScaleInterval(0.5, (1, 1, 1, 0)))
        self.sequence.start()
        self.sequence.setDoneEvent("splash-finished")
        self.app.accept("splash-finished", self.go_to_menu)

    def go_to_menu(self):
        self.app.ignore("splash-finished")
        self.app.state_manager.replace(MainMenuState)

    def exit(self):
        self.sequence.finish()
        self.progress_bar.destroy()
        self.splash.destroy()
        old_win = self.app.win
        self.app.closeWindow(old_win)
        sleep(0.3)  # TODO: cleaner version ? A clear cut between windows is nicer
        # than the flicker that happens without it
        props = WindowProperties()
        props.setUndecorated(False)
        props.setSize(self.app.pipe.getDisplayWidth(), self.app.pipe.getDisplayHeight())
        props.setFullscreen(True)
        self.app.openDefaultWindow(props=props)
        self.app.set_background_color(0, 0, 0)
