import uuid
from typing import Callable

from direct.interval.Interval import Interval
from direct.showbase.ShowBaseGlobal import ClockObject

from space_flight import EPSILON_TOLERANCE


class GameTimeManager:
    """
    A class to store the game's state and handle the time
    """

    def __init__(self, game, pause_on_init: bool = True):
        self.game = game
        # The game is not created at hte first frame since there are
        # splash and menu states => Account for that delay in the initial pause time
        self.time_in_pause_s = ClockObject.getGlobalClock().getFrameTime()
        self.real_time_at_last_pause_s = 0.0
        self.game_time_at_last_pause_s = 0.0
        if pause_on_init:
            self.pause()

    def resume(self):
        """
        Store the time spent during the pause
        """
        self.time_in_pause_s += (
            ClockObject.getGlobalClock().getFrameTime() - self.real_time_at_last_pause_s
        )

    def pause(self):
        """
        Store the real world and game world clocks at the time of the pause action
        """
        self.real_time_at_last_pause_s = ClockObject.getGlobalClock().getFrameTime()
        self.game_time_at_last_pause_s = self.get_current_time()

    def get_current_time(self) -> float:
        """
        Gets the time of the current frame

        :return: The time stamp of the current frame
        """
        if self.game.is_paused:
            time_s = self.game_time_at_last_pause_s
        else:
            time_s = ClockObject.getGlobalClock().getFrameTime() - self.time_in_pause_s

        return time_s

    def get_time_step(self) -> float:
        """
        Gets the time elapsed since the last frame

        :return: The time step
        """
        if self.game.is_paused:
            return 0.0
        else:
            return ClockObject.getGlobalClock().getDt()

    def get_average_frame_rate(self) -> float:
        """
        Gets the average frame rate.
        Always return a strictly positive value to avoid diveide by zero errors

        TODO: Take pauses/start menu into account ?

        :return: The average frame rate
        """
        average_frame_rate = max(
            ClockObject.getGlobalClock().getAverageFrameRate(), EPSILON_TOLERANCE
        )
        return average_frame_rate

    def clean(self):
        """
        Cleans the GameTimeManager object
        """
        self.game = None


class IntervalManager:
    """
    A class to handle the creation, destruction and pausing/resuming of time intervals
    """

    def __init__(self, game, pause_on_init: bool = True):
        self.active_intervals: list[Interval] = []
        self.game = game
        if pause_on_init:
            self.pause()

    def play_interval(self, interval: Interval):
        """
        - Adds an interval to the list of active intervals
        - Prepares its removal when it's done
        - Launches it

        :param interval: The interval to play
        """
        event_name = f"interval-done-{id(interval)}"
        interval.setDoneEvent(event_name)

        self.game.app.acceptOnce(event_name, self._on_interval_done, [interval])

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

    def clean(self):
        """
        Cleans the IntervalManager object
        """
        self.game = None
        self.active_intervals = None


class DelayedMethodManager:
    """
    A class to mimic the doMethodLater feature of panda3d while allowing pauses
    """

    def __init__(self, game):
        self.game = game
        self.methods_to_run_dict = {}

    def do_method_later(
        self, delay_s: float, name: str, method: Callable, extra_args: list = None
    ):
        """
        Schedule a method to run at some time in the future

        :param delay_s: The time to wait before running the method
        :param name: The name of the method
        :param method: The method itself
        :param extra_args: extra arguments for the method
        """
        extra_args = extra_args if extra_args is not None else []
        uid = uuid.uuid4()
        self.methods_to_run_dict[name + str(uid)] = {
            "delay_s": delay_s,
            "method": method,
            "extra_args": extra_args,
        }

    def update(self):
        """
        Decrease timers for all registered methods and launch them if their timers
        reach zero
        """
        if not self.game.is_paused:
            dt = self.game.game_time.get_time_step()
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

    def clean(self):
        """
        Cleans the DelayedMethodManager object
        """
        self.game = None
        self.methods_to_run_dict = None
