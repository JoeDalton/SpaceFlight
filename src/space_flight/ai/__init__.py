from enum import Enum, auto

import numpy as np

TARGET_DISTANCE_TOLERANCE_M = 1.0
INTERACT_MAX_DISTANCE_M = 2000.0

REFERENCE_VELOCITY_MPS = 1000


class Intent(Enum):
    """
    Definition of the possile intent states
    """

    ENGAGE = auto()
    EVADE = auto()
    DISENGAGE = auto()
    REGROUP = auto()
    PATROL = auto()
    IDLE = auto()


class Personality:
    """
    Definition of pre-baked bot personalities
    """

    # TODO better personality. Optimize ?
    DEFAULT = {
        "tactician": {
            "min_fighting_shape": 2,
            "min_engagement_score": 0.5,
            "primary_target_engagement_multiplier": 5.0,
            "max_threat_score": 0.98,
            "hunter_cutoff_distance": 1300.0,
            "hunter_angular_focus": 0.3,
            "prey_cutoff_distance": 1300.0,
            "prey_angular_focus": 1.0,
            "commitment_times": {
                Intent.ENGAGE: 10.0,
                Intent.EVADE: 1.5,
                Intent.DISENGAGE: 5.0,
                Intent.REGROUP: 3.0,
                Intent.PATROL: 3.0,
                Intent.IDLE: 0.1,
            },
        },
        "navigator": {
            "fire": {
                "minimimum_window_duration_s": 0.5,
                "maximum_distance_m": 600,
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
            },
            "intercept": {
                "lead_time_s": 1.5,
                "maximum_duration_s": 10.0,
                "minimum_cos_angle": np.cos(np.deg2rad(30)),
            },
            "extend": {
                "minimum_duration_s": 0.5,
                "maximal_time_in_spiral_s": 5.0,
                "minimum_closing_speed_mps": 20.0,
                "maximal_lateral_speed_mps": 100.0,
            },
            "reposition": {"minimum_time_to_overshoot_s": 1.5},
        },
        "pilot": {
            "angle_throttle_exponent": 0.5,
            "distance_throttle_exponent": 1.1,
            "minimum_throttle": 0.05,
        },
    }

    # Doesn't defends itself nor attacks
    SCAPEGOAT = {
        "tactician": {
            "min_fighting_shape": 0.0,
            "min_engagement_score": 2.0,
            "primary_target_engagement_multiplier": 5.0,
            "max_threat_score": 2.0,
            "hunter_cutoff_distance": 1300.0,
            "hunter_angular_focus": 0.7,
            "prey_cutoff_distance": 1300.0,
            "prey_angular_focus": 1.0,
            "commitment_times": {
                Intent.ENGAGE: 3.0,
                Intent.EVADE: 1.0,
                Intent.DISENGAGE: 5.0,
                Intent.REGROUP: 3.0,
                Intent.PATROL: 3.0,
                Intent.IDLE: 0.1,
            },
        },
        "navigator": {
            "fire": {
                "minimimum_window_duration_s": 0.5,
                "maximum_distance_m": 600,
                "maximum_angle_rad": np.deg2rad(5),
                "minimum_cos_angle": np.cos(np.deg2rad(5)),
            },
            "attack": {
                "lead_time_s": 0.5,
                "maximum_duration_s": 5.0,
                "minimum_cos_angle": np.cos(np.deg2rad(20)),
                "maximum_distance_m": 800,
            },
            "intercept": {
                "lead_time_s": 1.5,
                "maximum_duration_s": 10.0,
                "minimum_cos_angle": np.cos(np.deg2rad(30)),
            },
            "extend": {
                "minimum_duration_s": 0.5,
            },
            "reposition": {"minimum_time_to_overshoot_s": 1.5},
        },
        "pilot": {
            "angle_throttle_exponent": 0.5,
            "distance_throttle_exponent": 1.1,
            "minimum_throttle": 0.0,
        },
    }
