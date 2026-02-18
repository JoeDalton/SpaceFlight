from time import sleep

from direct.gui.OnscreenImage import OnscreenImage
from direct.interval.IntervalGlobal import Sequence
from panda3d.core import TransparencyAttrib, WindowProperties

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.base_state import BaseState
from space_flight.main_menu.main_menu_state import MainMenuState
from space_flight.ui.progress_bar import ProgressBar


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

        self.splash = OnscreenImage(
            image=str(DATAFILES_PATH / "sprites/splash_screen/splash.png"),
            scale=(1280 / 544, 1, 1),
            parent=self.app.aspect2d,
        )

        self.splash.setTransparency(TransparencyAttrib.MAlpha)
        self.splash.setColor(1, 1, 1, 1)

        blurbs = [
            "Mustering crews",
            "Setting hyperspace coordinates",
            "Loading proton torpedos",
            "Scanning derelict ship",
            "Fixing the Falcon's hyperdrive",
            "Calibrating laser cannon",
            "Clearing flight deck",
            "Scrambling interceptors",
            "Priming deflector shields",
            "Forming squadrons",
        ]

        self.progress_bar = ProgressBar(app=self.app, parent=self.splash, blurbs=blurbs)
        # List of assets to load
        self.assets_to_load = [
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
            ("model", "models/ship.bam"),
            ("model", "models/station.bam"),
            ("texture", "textures/space.png"),
            ("texture", "textures/ui.png"),
        ]

        self.loaded_assets = {}
        self.total_assets = len(self.assets_to_load)

        # Start loading task
        self.app.taskMgr.add(self.load_assets_task_placeholder, "load-assets-task")

    def load_assets_task(self, task):
        if not self.assets_to_load:
            # Done loading
            self.app.taskMgr.remove("load-assets-task")
            self.on_loading_finished()
            return task.done

        asset_type, path = self.assets_to_load.pop(0)

        if asset_type == "model":
            self.loaded_assets[path] = self.app.loader.loadModel(path)

        elif asset_type == "texture":
            self.loaded_assets[path] = self.app.loader.loadTexture(path)

        # Update progress
        progress = (self.total_assets - len(self.assets_to_load)) / self.total_assets
        self.progress_bar["value"] = progress * 100

        return task.cont

    def load_assets_task_placeholder(self, task):
        # simulate delay without blocking
        if not hasattr(task, "next_load_time"):
            task.next_load_time = task.time + 0.01

        if task.time < task.next_load_time:
            return task.cont

        if not self.assets_to_load:
            self.app.taskMgr.remove("load-assets-task")
            self.on_loading_finished()
            return task.done

        asset_type, path = self.assets_to_load.pop(0)

        progress = (self.total_assets - len(self.assets_to_load)) / self.total_assets

        self.progress_bar.update(value=progress)

        task.next_load_time = task.time + 0.01
        return task.cont

    def on_loading_finished(self):
        self.sequence = Sequence(self.splash.colorScaleInterval(0.5, (1, 1, 1, 0)))
        self.sequence.start()
        self.sequence.setDoneEvent("splash-finished")
        self.app.accept("splash-finished", self.go_to_menu)

    def go_to_menu(self):
        self.app.ignore("splash-finished")
        self.app.state_manager.change_state(MainMenuState)

    def exit(self):
        self.sequence.finish()
        self.progress_bar.destroy()
        self.splash.destroy()
        old_win = self.app.win
        self.app.closeWindow(old_win)
        sleep(0.5)  # TODO: cleaner version ? A clear cut between windows is nicer
        # than the flicker that happens without it
        props = WindowProperties()
        props.setUndecorated(False)
        props.setSize(self.app.pipe.getDisplayWidth(), self.app.pipe.getDisplayHeight())
        props.setFullscreen(True)
        self.app.openDefaultWindow(props=props)
        self.app.set_background_color(0, 0, 0)
