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

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Destroyed destructible object: {self.name}")


class Destructibles:
    """
    A class to account for all destructible objects, and handle their deaths
    """

    def __init__(self, app):
        # For some reason the task does not appear in the task manager but still runs...
        self.app = app
        self.alive_objects: List[Destructible] = []
        self.app.taskMgr.add(self.handle_deaths_task, "Handle deaths")

    def handle_deaths_task(self, task):
        """
        Check the health of all destructible and kill them if necessary
        TODO Very expensive !!
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
            destructible.clear_tasks()
            destructible.clean()
            # TODO Call an explosion animation at the scale
            # and position of the destructible
        # Drop references to the dead objects
        newly_dead_objects = []

        return task.cont
