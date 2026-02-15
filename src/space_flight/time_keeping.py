from enum import Enum, auto
from typing import Callable

from direct.interval.Interval import Interval
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject


class GameStates(Enum):
    """
    Definition of the possile game states
    """

    # IDLE = auto()
    # LOADING = auto()
    PLAYING = auto()
    PAUSED = auto()


class GameTimeManager:
    """
    A class to store the game's state and handle the time
    """

    def __init__(self, app: ShowBase):
        self.state = GameStates.PAUSED
        self.app = app
        self.time_in_pause_s = 0.0
        self.real_time_at_last_pause_s = 0.0
        self.game_time_at_last_pause_s = 0.0

    def toggle_pause(self):
        """
        Pauses the game when it's playing and vice-versa
        """
        if self.state == GameStates.PAUSED:
            self._set_play()
        elif self.state == GameStates.PLAYING:
            self._set_pause()
        else:
            pass

    def _set_play(self):
        """
        Passes the game's state to "PLAYING" and resumes the game's intervals
        """
        self.state = GameStates.PLAYING
        self.app.interval_manager.resume()
        self.time_in_pause_s += (
            ClockObject.getGlobalClock().getFrameTime() - self.real_time_at_last_pause_s
        )

    def _set_pause(self):
        """
        Passes the game's state to "PAUSED" and pauses the game's intervals
        """
        self.real_time_at_last_pause_s = ClockObject.getGlobalClock().getFrameTime()
        self.game_time_at_last_pause_s = self.get_current_time()
        self.state = GameStates.PAUSED
        self.app.interval_manager.pause()

    def get_current_time(self) -> float:
        """
        Gets the time of the current frame

        :return: The time stamp of the current frame
        """
        if self.state == GameStates.PLAYING:
            time_s = ClockObject.getGlobalClock().getFrameTime() - self.time_in_pause_s
        elif self.state == GameStates.PAUSED:
            time_s = self.game_time_at_last_pause_s
        else:
            print("Whaaaat ?")
        return time_s

    def get_time_step(self) -> float:
        """
        Gets the time elapsed since the last frame

        :return: The time step
        """
        if self.state == GameStates.PLAYING:
            return ClockObject.getGlobalClock().getDt()
        else:
            return 0.0

    def get_average_frame_rate(self) -> float:
        """
        Gets the average frame rate

        TODO: Take pauses/start menu into account ?

        :return: The average frame rate
        """
        return ClockObject.getGlobalClock().getAverageFrameRate()


class IntervalManager:
    """
    A class to handle the creation, destruction and pausing/resuming of time intervals
    """

    def __init__(self, app: ShowBase):
        self.active_intervals: list[Interval] = []
        self.app = app

    def play_interval(self, interval: Interval):
        """
        - Adds an interval to the list of active intervals
        - Prepares its removal when it's done
        - Launches it

        :param interval: The interval to play
        """
        event_name = f"interval-done-{id(interval)}"
        interval.setDoneEvent(event_name)

        self.app.acceptOnce(event_name, self._on_interval_done, [interval])

        self.active_intervals.append(interval)
        interval.start()

    def _on_interval_done(self, interval: Interval):
        """
        Remove an interval from the active list

        :param interval: _description_
        """
        if interval in self.active_intervals:
            self.active_intervals.remove(interval)

    def pause(self):
        """
        Pauses all active intervals
        """
        for i in self.active_intervals:
            i.pause()

    def resume(self):
        """
        Resumes all active intervals
        """
        for i in self.active_intervals:
            i.resume()


class DelayedMethodManager:
    """
    A class to mimic the doMethodLater feature of panda3d while allowing pauses
    """

    def __init__(self, app: ShowBase):
        self.app = app
        self.methods_to_run_dict = {}
        self.app.taskMgr.add(self.update, "update_delayed_functions")

    def do_method_later(
        self, delay_s: float, name: str, method: Callable, extra_args: list = []
    ):
        """
        Schedule a method to run at some time in the future

        :param delay_s: The time to wait before running the method
        :param name: The name of the method
        :param method: The method itself
        :param extra_args: extra arguments for the method
        """
        self.methods_to_run_dict[name] = {
            "delay_s": delay_s,
            "method": method,
            "extra_args": extra_args,
        }

    def update(self, task):
        """
        Decrease timers for all registered methods and launch them if their timers
        reach zero
        """
        if self.app.game_time.state == GameStates.PLAYING:
            dt = self.app.game_time.get_time_step()
            methods_to_pop = []
            for name in self.methods_to_run_dict.keys():
                self.methods_to_run_dict[name]["delay_s"] -= dt
                if self.methods_to_run_dict[name]["delay_s"] <= 0.0:
                    methods_to_pop.append(name)
                    method = self.methods_to_run_dict[name]["method"]
                    extra_args = self.methods_to_run_dict[name]["extra_args"]
                    method(*extra_args)
            for name in methods_to_pop:
                self.methods_to_run_dict.pop(name)
        return task.cont
