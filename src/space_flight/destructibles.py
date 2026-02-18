import logging
from typing import Callable, List

from space_flight import DEBUG_DELETION

LOGGER = logging.getLogger()


class Destructible:
    """
    A class for destructible objects in the simulation
    """

    def __init__(self, app):
        self.app = app
        self.tasks = []
        self.app.destructibles.alive_objects.append(self)

    def add_task(self, method: Callable, task_name: str):
        """
        Add a task linked to this object

        :param method: the method to be called by the task
        :param task_name: The name of the task
        """
        self.tasks.append(self.app.taskMgr.add(method, task_name))

    def clear_tasks(self):
        """
        Remove all tasks linked to this object
        """
        for task in self.tasks:
            self.app.taskMgr.remove(task)
        self.tasks = []

    def clean(self):
        """
        Remove nodes and attributes, to be done for each subclass
        """
        raise NotImplementedError

    def get_health(self):
        """
        Find the health of the destructible object, to be done for each subclass
        """
        raise NotImplementedError

    def play_death(self):
        """
        Plays the death animation of the destructible object,
        to be done for each subclass
        """
        raise NotImplementedError

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Destroyed destructible object: {self.name}")


class Destructibles:
    """
    A class to account for all destructible objects, and handle their deaths
    """

    def __init__(self):
        self.alive_objects: List[Destructible] = []

    def handle_deaths(self):
        """
        Check the health of all destructible and kill them if necessary
        TODO Expensive ?
        """
        still_alive_objects: List[Destructible] = []
        newly_dead_objects: List[Destructible] = []

        # Loop over every destructible and find if they are still alive
        for destructible in self.alive_objects:
            if destructible.get_health() <= 0.0:
                newly_dead_objects.append(destructible)
            else:
                still_alive_objects.append(destructible)
        # Reset the list of destructibles with only those who are still alive
        self.alive_objects = []
        self.alive_objects = still_alive_objects
        # Handle the death of the newly dead objects
        for destructible in newly_dead_objects:
            destructible.play_death()
            destructible.clear_tasks()
            destructible.clean()
        # Drop references to the dead objects
        newly_dead_objects = []
