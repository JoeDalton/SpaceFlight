import logging
from enum import Enum, auto

import numpy as np

TARGET_DISTANCE_TOLERANCE_M = 1.0
INTERACT_MAX_DISTANCE_M = 10000.0
REFERENCE_ERROR_VELOCITY_MPS = 100
ROLL_TOLERANCE = 1e-2
HALF_PI = np.pi / 2

LOGGER = logging.getLogger()


class Intent(Enum):
    """
    Definition of the possile intent states
    """

    ENGAGE = auto()
    EVADE = auto()
    DISENGAGE = auto()
    REGROUP = auto()
    PATROL = auto()
    FORMATION = auto()
    IDLE = auto()


class Formation:
    """
    A class for wing formations
    """

    RELATIVE_POSITIONS = [
        np.array([0, 0, 0]),
        np.array([30, -60, 0]),
        np.array([-30, -60, 0]),
        np.array([60, -120, 0]),
        np.array([0, -180, 10]),
        np.array([-60, -120, 0]),
        np.array([0, -50, 30]),
        np.array([0, -50, -30]),
        np.array([0, -120, 60]),
        np.array([0, -120, -60]),
    ]

    def __init__(self):
        self.ship_ids = []

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
            if len(self.ship_ids) < len(self.RELATIVE_POSITIONS):
                self.ship_ids.append(ship_id)
                in_formation = True
            else:
                LOGGER.warning("Ship cannot be added to a full formation")
        else:
            # Pop the ship if it is already in formation
            if ship_id in self.ship_ids:
                self.remove_ship(ship_id)
            # Set ship as leader
            if len(self.ship_ids) < len(self.RELATIVE_POSITIONS):
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


class Personality:
    """
    Definition of pre-baked bot personalities
    """

    # TODO better personality. Optimize ?
    FIGHTER_DEFAULT = {
        "tactician": {
            "min_fighting_shape": 2,
            "min_engagement_score": 0.5,
            "primary_target_engagement_multiplier": 5.0,
            "max_threat_score": 0.98,
            "hunter_cutoff_distance": 3000.0,
            "hunter_angular_focus": 0.3,
            "prey_cutoff_distance": 800.0,
            "prey_angular_focus": 1.0,
            "intent_update_delay": 0.5,
            "commitment_times": {
                Intent.ENGAGE: 10.0,
                Intent.EVADE: 1.5,
                Intent.DISENGAGE: 5.0,
                Intent.REGROUP: 3.0,
                Intent.PATROL: 3.0,
                Intent.FORMATION: 3.0,
                Intent.IDLE: 0.1,
            },
        },
        "navigator": {
            "patrol": {"speed_mps": 100.0},
            "idle": {"speed_mps": 0.0},
            "regroup": {"speed_mps": 100.0},
            "turning": {"speed_mps": 50.0},
            "speeding": {"speed_mps": 2000.0},
            "formation": {
                "ideal_distance_m": 300.0,
                "speed_distance_slope": 0.01,
                "collision_avoidance_contribution_factor": 0.015,
            },
            "fire": {
                "minimimum_window_duration_s": 0.5,
                "maximum_distance_m": 1000,
                "maximum_angle_rad": np.deg2rad(5),
                "minimum_cos_angle": np.cos(np.deg2rad(5)),
            },
            "attack": {
                "lead_time_s": 1.0,
                "lag_time_s": 0.5,
                "maximum_duration_s": 5.0,
                "minimum_cos_angle": np.cos(np.deg2rad(20)),
                "maximum_distance_m": 800,
                "cap_bias": 1.0,
                "lead_bias": 1.0,
                "lag_bias": 1.0,
                "cap_cutoff_distance_m": 300.0,
                "lead_high_cutoff_distance_m": 350.0,
                "lead_low_cutoff_distance_m": 100.0,
                "lag_cutoff_distance_m": 150.0,
                "lead_lag_cutoff_slope": 0.02,
                "cap_lead_cutoff_slope": 0.04,
                "ideal_distance_m": 200.0,
                "speed_distance_slope": 0.01,
            },
            "intercept": {
                "lead_time_s": 1.5,
                "maximum_duration_s": 10.0,
                "minimum_cos_angle": np.cos(np.deg2rad(30)),
            },
            "extend": {
                "minimum_duration_s": 3.0,
                "maximal_time_in_spiral_s": 5.0,
                "minimum_closing_speed_mps": 100.0,
                "maximal_lateral_speed_mps": 50.0,
            },
            "reposition": {"minimum_time_to_overshoot_s": 0.5},
        },
        "pilot": {
            "sample_time_s": 0.1,
            "minimum_throttle": 0.01,
            "yaw_kp": 1.0,
            "yaw_ki": 0.0,
            "yaw_kd": 0.0,
            "pitch_kp": -1.0,
            "pitch_ki": 0.0,
            "pitch_kd": 0.0,
            "roll_kp": -0.5,
            "roll_ki": 0.0,
            "roll_kd": 0.0,
            "throttle_kp": 2.0,
            "throttle_ki": 0.1,
            "throttle_kd": 0.0,
        },
    }

    TURRET_DEFAULT = {
        "tactician": {
            "min_engagement_score": 0.5,
            "primary_target_engagement_multiplier": 5.0,
            "hunter_cutoff_distance": 900.0,
            "hunter_angular_focus": 0.3,
            "intent_update_delay": 0.5,
            "commitment_times": {
                Intent.ENGAGE: 10.0,
                Intent.IDLE: 0.1,
            },
        },
        "navigator": {
            "fire": {
                "maximum_distance_m": 1000,
                "maximum_angle_rad": np.deg2rad(5),
                "minimum_cos_angle": np.cos(np.deg2rad(5)),
            },
            "attack": {
                "lead_time_s": 0.1,
            },
        },
        "pilot": {
            "sample_time_s": 0.1,
            "yaw_kp": 3.0,
            "yaw_ki": 0.0,
            "yaw_kd": 0.0,
            "pitch_kp": -3.0,
            "pitch_ki": 0.0,
            "pitch_kd": 0.0,
        },
    }
