import logging

import numpy as np

LOGGER = logging.getLogger()


class Formation:
    """
    A class for wing formations
    """

    FIGHTER_SCALE_M = 30
    CAPITAL_SHIP_SCALE_M = 500

    ARROWHEAD_POSITIONS = [
        np.array([0, 0, 0]),
        np.array([1, -2, 0]),
        np.array([-1, -2, 0]),
        np.array([2, -4, 0]),
        np.array([-2, -4, 0]),
        np.array([3, -6, 0]),
        np.array([-3, -6, 0]),
    ]
    DIAMOND_POSITIONS = [
        np.array([0, 0, 0]),
        np.array([1, -2, 0]),
        np.array([-1, -2, 0]),
        np.array([2, -4, 0]),
        np.array([-2, -4, 0]),
        np.array([1, -6, 0]),
        np.array([-1, -6, 0]),
        np.array([0, -8, 0]),
    ]
    AROUND_DIAMOND_POSITIONS = [
        np.array([0, 0, 0]),
        np.array([2, 0, 0]),
        np.array([-2, 0, 0]),
        np.array([1, -2, 0]),
        np.array([-1, -2, 0]),
        np.array([0, -4, 0]),
        np.array([1, 2, 0]),
        np.array([-1, 2, 0]),
        np.array([0, 4, 0]),
    ]

    def __init__(
        self,
        scale_m: float | None = None,
        shape: int | None = None,
    ):
        self.ship_ids = []
        if scale_m is None:
            scale_m = self.FIGHTER_SCALE_M
        if shape is None:
            shape = "arrowhead"

        # Set the relative positions in the formation
        if shape == "arrowhead":
            self.relative_positions = self.ARROWHEAD_POSITIONS
        elif shape == "diamond":
            self.relative_positions = self.DIAMOND_POSITIONS
        elif shape == "around_diamond":
            self.relative_positions = self.AROUND_DIAMOND_POSITIONS
        else:
            raise NotImplementedError(f"Unknown formation shape {shape}")

        # Set the scale of the formation
        for item in self.relative_positions:
            item *= scale_m

    def get_ship_index(self, ship_id):
        """
        Returns the position of a given ship in the formation
        """
        ship_index = None
        for index, candidate_id in enumerate(self.ship_ids):
            if ship_id == candidate_id:
                ship_index = index
                break
        return ship_index

    def add_ship(self, ship, leader=False):
        """
        Adds a ship to the formation. By default, it is added as the
        last wingman, but there is the option to set it as leader
        If the leader option is True and the ship is already there, it is
        simply promoted.
        """
        ship_id = ship.id
        in_formation = False
        if not leader:
            if ship_id in self.ship_ids:
                # Ship is already in formation, do nothing
                return
            # Add ship as the last wingman
            if len(self.ship_ids) < len(self.relative_positions):
                self.ship_ids.append(ship_id)
                in_formation = True
            else:
                LOGGER.warning("Ship cannot be added to a full formation")
        else:
            # Pop the ship if it is already in formation
            if ship_id in self.ship_ids:
                self.remove_ship(ship_id)
            # Set ship as leader
            if len(self.ship_ids) < len(self.relative_positions):
                self.ship_ids.insert(index=0, object=ship_id)
                in_formation = True
            else:
                LOGGER.warning("Ship cannot be added to a full formation")
        if in_formation:
            ship.formation = self

    def remove_ship(self, ship_id):
        """
        Removes a ship from the formation. Typical case is in the event of ship death
        """
        index_to_remove = self.get_ship_index(ship_id=ship_id)
        self.ship_ids.pop(index_to_remove)
