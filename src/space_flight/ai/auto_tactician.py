import logging

from space_flight import DEBUG_DELETION

LOGGER = logging.getLogger()


class AutoTactician:
    """
    TODO
    Finds the proper strategy for a bot:
    - Select the most valuable target (enemy to kill, friend to escort,
        patrol to do, should be scriptable ?)
    - Weigh the behaviour forces
    - The weights could depend on an aggressive/defensive/cowardly personnality
    - They may depend on the situation and/or a scenario
    """

    def __init__(self, ship):
        self.ship = ship

    def think(self):
        """
        Example of result

        behaviours = [
            {
                "action": "flee_from_target",
                "target": <some asteroid that's too close>,
                "weight": 10,
            },
            {
                "action": "evade_target",
                "target": <a menacing enemy ship>,
                "weight": 5,
            },
            {
                "action": "follow_waypoints", # Only one of those please
                "weight": 1,
            },
            {
                "action": "chase_target",
                "target": <a vulnerable enemy>, # Or a leader to follow
                "weight": 1,
            },
        ]

        Then:
        - The navigator uses the distance associated with the most weighted behaviour
        - The navigator makes a weighted average of all behaviour directions. If
            the average is null, return NO_DIRECTION

        TODO: For the flee problem, use a global array of all collidable objects ?
        Or use the collision system of panda3d ?
        Aaaaaaaaaaaaaaaaaaah, paniiiiiiic !!!

        """
        if self.ship.parent.name == "tie_2":
            my_thoughts = [
                {
                    "action": "follow_waypoints",
                    "weight": 1,
                },
            ]
        else:
            my_thoughts = [
                {
                    "action": "chase_target",
                    "target": self.ship.app.bot2.ship,
                    "weight": 1,
                },
            ]

        return my_thoughts

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")
