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


class AttackMode(Enum):
    """
    How a bot attacks a target once its tactician has chosen Intent.ENGAGE.

    Carried in target_dict["attack_mode"] (the tactician decides, the
    navigator executes). PURSUIT is the constant-angle chase, good against
    agile prey; STRAFE is a committed run-in/fire/break/reposition cycle for
    slow or immobile targets; BOMB overflies a slow/immobile target and drops
    a bomb along the belly; ORBIT keeps a target abeam on a capital ship's
    turret flank.
    """

    PURSUIT = auto()
    STRAFE = auto()
    ORBIT = auto()
    BOMB = auto()


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
            # Below this target mobility, engage with a STRAFE run rather than a
            # PURSUIT chase (a slow/immobile prey can't be chased sensibly).
            "strafe_mobility_threshold": 0.35,
            # Weapon-suitability scoring: spend a limited bomb only on a target
            # that is BOTH tough and valuable (worth = hardness * value), when
            # stationary enough and supply allows. S_bomb > S_gun -> BOMB.
            # (Ramps use smooth_step_up.)
            "bomb_scoring": {
                "hardness_step": 5000.0,  # health+shield read as "hard" beyond this
                "hardness_slope": 0.005,
                "value_step": 3.0,  # on the primary-target multiplier (1 vs 5)
                "value_slope": 1.0,
                "supply_step": 2.0,  # bombs remaining for a strong supply factor
                "supply_slope": 1.0,
                "gun_base": 0.3,  # guns are always somewhat suitable
                "gun_soft": 0.7,  # ...and great against soft targets
                "bomb_scale": 1.5,  # overall bomb eagerness
            },
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
            "patrol": {
                "speed_mps": 100.0,
                "waypoint_meeting_tolerance_m": 50.0,
            },
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
            # Strafing run: a committed ingress -> attack -> break -> reposition
            # cycle for slow/immobile targets. The corridor + altitude-floor keys
            # only take effect when the target carries surface info (surface-mounted
            # preys); otherwise the run is a straight open-space pass.
            "strafe": {
                "attack_distance_m": 700.0,  # ingress -> attack transition
                "break_distance_m": 150.0,  # attack -> break (reached point-blank)
                # The attack presses in until point-blank; it only peels off early
                # if it is about to overshoot or has stalled (can't close). There is
                # no fixed attack timer.
                "stall_time_s": 2.5,  # grace before the stall check applies
                "minimum_closing_speed_mps": 30.0,  # below this = stalled -> break
                # Fly at where the target will be on arrival: lead by the closing
                # time (distance / closing_speed), capped so a slow closure at long
                # range doesn't aim wildly ahead (it converges to the exact lead as
                # the gap shrinks).
                "max_lead_time_s": 5.0,
                "break_duration_s": 1.5,  # committed break, no immediate re-lock
                "reposition_distance_m": 900.0,  # reposition -> ingress when beyond
                "reposition_min_duration_s": 3.0,  # ...and committed at least this long
                #   so the run flies out and swings around before the next pass
                # Speeds are fractions of the ship's own max_speed_mps: absolute
                # values well above it just pin the throttle and push the explicit
                # integrator into divergence (see Ship._sanitize_state).
                "ingress_speed_factor": 1.0,
                "attack_speed_factor": 0.85,
                "break_speed_factor": 0.6,
                "reposition_speed_factor": 1.0,
                "fire_min_cos_angle": np.cos(np.deg2rad(15)),  # wider than pursuit
                "run_altitude_m": 150.0,  # corridor altitude above the surface
                "altitude_floor_m": 60.0,  # hard recovery floor (surface targets)
                "corridor_avoidance_factor": 0.1,  # down-weight sensor in corridor
                "swivel_amplitude": 0.0,  # lateral weave strength (added to dir)
                "swivel_frequency_hz": 0.5,
                "swivel_distance_scale_m": 800.0,  # amplitude ramps within this range
            },
            # Bombing run: overfly a slow/immobile target and release a bomb along
            # the belly (-Z). A committed straight, wings-level leg is flown for
            # accuracy; the release solver times the drop off the bomb's (linear,
            # no-gravity) velocity. Belly-aiming uses the pilot up-reference.
            "bomb": {
                "run_distance_m": 600.0,  # ingress -> run (straight leg begins)
                # (bomb launch speed is the BOMB_SPEED_MPS global in bomb_launcher,
                # shared with the release solver.)
                "min_cos_release": np.cos(np.deg2rad(12)),  # bomb-velocity cone
                "max_release_distance_m": 300.0,  # only release within this range
                "break_duration_s": 1.5,  # committed climbing break
                "reposition_distance_m": 900.0,
                "reposition_min_duration_s": 3.0,
                "ingress_speed_factor": 1.0,
                "run_speed_factor": 0.85,  # steady leg, a touch slower
                "break_speed_factor": 0.6,
                "reposition_speed_factor": 1.0,
            },
        },
        "pilot": {
            "sample_time_s": 0.1,
            "minimum_throttle": 0.2,
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

    TRACTOR_BEAM_DEFAULT = {
        # Aiming (target selection / lead aim / steering) is identical to a
        # turret's: a tractor beam is just another tracking mount.
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
        # Grab behaviour (as opposed to the projector's fixed hardware specs, which
        # live in its model config): how long it commits to and holds a prey, and
        # the relative speed at which the prey wrenches free.
        "tractor_beam": {
            "min_grab_time_s": 2.0,
            "max_grab_time_s": 15.0,
            "release_speed_mps": 150.0,
            "regrab_cooldown_s": 3.0,
        },
    }

    CAPITAL_SHIP_DEFAULT = {
        "tactician": {
            "min_fighting_shape": 2,
            "intent_update_delay": 5,
            "commitment_times": {
                Intent.ENGAGE: 10.0,
                Intent.DISENGAGE: 5.0,
                Intent.REGROUP: 3.0,
                Intent.PATROL: 3.0,
                Intent.FORMATION: 3.0,
                Intent.IDLE: 0.1,
            },
        },
        "navigator": {
            "patrol": {
                "speed_mps": 80.0,
                "waypoint_meeting_tolerance_m": 200.0,
            },
            "idle": {"speed_mps": 0.0},
            "regroup": {"speed_mps": 80.0},
            "turning": {"speed_mps": 30.0},
            "speeding": {"speed_mps": 2000.0},
            "formation": {
                "ideal_distance_m": 300.0,
                "speed_distance_slope": 0.01,
                "collision_avoidance_contribution_factor": 0.015,
            },
            "attack": {
                "relative_direction": np.array([0, 1, 0]),
                "distance_m": 500,
                "speed_mps": 50,
            },
            # Orbit: hold a constant standoff from the target's oriented bounding
            # box and drive tangentially, so the shape follows the target (a circle
            # for compact targets, a racetrack for long ones) and the target stays
            # abeam on the turret flank.
            "orbit": {
                "standoff_clearance_m": 300.0,  # added to the target half-width
                "orbit_speed_mps": 40.0,
                "radial_gain": 0.01,  # how hard to correct the standoff distance
                "direction": 1.0,  # orbit sense s in {+1, -1}, sets the turret side
                "altitude_stagger_m": 50.0,  # sit off the exact target plane
                "vertical_gain": 0.01,
                # Placeholder floor keeping the bow/stern caps flyable for a slow
                # ship. TODO derive from the ship's real min turn radius at speed.
                "min_turn_radius_m": 400.0,
            },
        },
        "pilot": {
            "sample_time_s": 0.2,
            "minimum_throttle": 0.2,
            "yaw_kp": 1.0,
            "yaw_ki": 0.0,
            "yaw_kd": 0.0,
            "pitch_kp": -1.0,
            "pitch_ki": 0.0,
            "pitch_kd": 0.0,
            "roll_kp": -1.0,
            "roll_ki": 0.0,
            "roll_kd": 0.0,
            "throttle_kp": 2.0,
            "throttle_ki": 0.1,
            "throttle_kd": 0.0,
        },
    }
