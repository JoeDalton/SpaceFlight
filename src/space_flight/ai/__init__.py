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
    Definition of the possible intent states
    """

    ENGAGE = auto()
    EVADE = auto()
    DISENGAGE = auto()
    REGROUP = auto()
    PATROL = auto()
    FORMATION = auto()
    IDLE = auto()
    DEFEND_MISSILE = auto()


class AttackMode(Enum):
    """
    How a bot attacks a target once its tactician has chosen Intent.ENGAGE.

    Carried in target_dict["attack_mode"] (the tactician decides, the
    navigator executes). PURSUIT: constant-angle chase of agile prey. STRAFE:
    committed run-in/fire/break/reposition cycle on a slow or immobile target.
    BOMB: overfly a slow/immobile target and drop a bomb from the belly.
    ORBIT: keep a target abeam on a capital ship's turret flank.
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
            # Against a slow primary target worth heavy ordnance, try a torpedo
            # (a stand-off shot) before a bomb (a long, exposed run), or the
            # other way round
            "prefer_torpedoes_to_bombs": True,
            # Weapon-suitability scoring of the heavy ordnance (bombs, and the
            # missiles meant for slow targets: torpedoes): spend it only on a
            # target that is BOTH tough and valuable (worth = hardness * value),
            # when stationary enough and supply allows. S_ordnance > S_gun -> the
            # ordnance. (Ramps use smooth_step_up.)
            "heavy_ordnance_scoring": {
                "hardness_step": 5000.0,  # health+shield read as "hard" beyond this
                "hardness_slope": 0.005,
                "value_step": 3.0,  # on the primary-target multiplier (1 vs 5)
                "value_slope": 1.0,
                "supply_step": 2.0,  # stock left for a strong supply factor
                "supply_slope": 1.0,
                "gun_base": 0.3,  # guns are always somewhat suitable
                "gun_soft": 0.7,  # ...and great against soft targets
                "ordnance_scale": 1.5,  # overall heavy ordnance eagerness
            },
            # Defend against an incoming missile once it is this close to impact
            "missile_defense_time_s": 3.0,
            "intent_update_delay": 0.5,
            "commitment_times": {
                Intent.ENGAGE: 10.0,
                Intent.EVADE: 1.5,
                Intent.DEFEND_MISSILE: 0.5,
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
                "stall_time_s": 6.0,
                "stall_deceleration_factor": 0.5,
                "min_speed_factor": 0.1,
                "progress_epsilon_m": 5.0,
            },
            "regroup": {"speed_mps": 100.0},
            "countermeasures": {"flare_range_fraction": 0.8},
            "turning": {"speed_mps": 50.0},
            "speeding": {"speed_mps": 2000.0},
            "formation": {
                "ideal_distance_m": 300.0,
                "speed_distance_slope": 0.01,
                "collision_avoidance_contribution_factor": 0.015,
            },
            "fire": {
                "maximum_distance_m": 1000,
                "minimum_cos_angle": np.cos(np.deg2rad(5)),
            },
            # Missiles and rockets (see FighterNavigator._fire_missile and
            # _fire_rocket), on top of the guns: missiles at primary targets
            # only, rockets at any target of their target_mobility (see
            # FighterTactician._choose_weapon)
            "ordnance": {
                # Launch a locked missile only within this fraction of its reach
                # (its launch speed times its life time)
                "missile_max_range_fraction": 0.5,
                # Hold fire while this many of our missiles home on the target
                "max_missiles_in_flight": 1,
                # Rockets are unguided: a tighter cone than the guns, around the
                # lead solution for the rocket's flight time, within gun range
                "rocket_fire_min_cos_angle": np.cos(np.deg2rad(3)),
            },
            "attack": {
                "lead_time_s": 1.0,
                "lag_time_s": 0.5,
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
                # Never slow below this fraction of the ship's max_speed_mps when
                # pursuing; the floor also caps collision avoidance's slowdown
                # (avoidance still steers) when minimum_speed_overrides_avoidance
                "minimum_speed_factor": 0.75,
                "minimum_speed_overrides_avoidance": True,
            },
            "extend": {
                "minimum_duration_s": 3.0,
                "maximum_time_in_spiral_s": 5.0,
                "minimum_closing_speed_mps": 100.0,
                "maximum_lateral_speed_mps": 50.0,
            },
            "reposition": {"minimum_time_to_overshoot_s": 0.5},
            # Strafing run (see FighterNavigator.strafe_target). The corridor and
            # altitude-floor keys only apply when the target carries surface info;
            # otherwise the run is a straight open-space pass.
            "strafe": {
                "attack_distance_m": 700.0,  # ingress -> attack transition
                "break_distance_m": 150.0,  # attack -> break (reached point-blank)
                "stall_time_s": 2.5,  # grace before the stall check applies
                "minimum_closing_speed_mps": 30.0,  # below this = stalled -> break
                # Cap on the closing-time lead, so a slow closure at long range
                # doesn't aim wildly ahead.
                "max_lead_time_s": 5.0,
                "break_duration_s": 1.5,  # committed break, no immediate re-lock
                "reposition_distance_m": 900.0,  # reposition -> ingress when beyond
                "reposition_min_duration_s": 3.0,  # ...and committed at least this long
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
            # Bombing run (see FighterNavigator.bomb_target). The bomb's launch
            # velocity comes from its launcher (OrdnanceLauncher.initial_velocity),
            # shared with the release solver.
            "bomb": {
                # Entry point distance behind the target along its track
                "entry_distance_m": 750.0,
                # Carrot look-ahead up the track line: long for the ingress (a
                # gentle cut onto the line), short for the belly-down approach/run
                # (tracks a turning target's line tightly).
                "line_lookahead_m": 300.0,
                "run_lookahead_m": 150.0,
                # "On the line" below lateral_tolerance_m of cross-track offset;
                # the approach falls back to the ingress past lateral_recovery_m.
                # The tolerance must keep the target inside the release cone at run
                # altitude (~sin(cone) * slant range).
                "lateral_tolerance_m": 30.0,
                "lateral_recovery_m": 80.0,
                # Overfly height. Must stay below the bomb's fall over its lifetime
                # (its launch speed_mps * life_time_s, see its configuration) or it
                # expires before reaching the target.
                "run_altitude_m": 100.0,
                # Below this target speed, the bomber's bearing defines the track
                "min_track_speed_mps": 5.0,
                # Approach -> run when the target is within this flight time (at the
                # bomber's current speed) and still on the line
                "lock_time_s": 2.0,
                "min_cos_release": np.cos(np.deg2rad(25)),  # bomb-velocity cone
                "max_release_distance_m": 450.0,  # only release within this range
                "break_duration_s": 1.0,  # committed break after the drop
                "reposition_distance_m": 1000.0,
                "reposition_min_duration_s": 3.0,
                "ingress_speed_factor": 1.0,
                "approach_speed_factor": 1.0,
                "run_speed_factor": 1.0,
                "break_speed_factor": 0.6,
                "reposition_speed_factor": 1.0,
            },
        },
        "pilot": {
            "sample_time_s": 0.1,
            "minimum_throttle": 0.2,
            # Energy protection below the navigator's speed floor: the yaw/pitch
            # rates ramp down to min_turn_authority over a range of
            # energy_protection_range_factor * max_speed_mps (see GenericShipPilot)
            "min_turn_authority": 0.8,
            "energy_protection_range_factor": 0.15,
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
                "stall_time_s": 12.0,
                "stall_deceleration_factor": 0.5,
                "min_speed_factor": 0.1,
                "progress_epsilon_m": 5.0,
            },
            "regroup": {"speed_mps": 80.0},
            "speeding": {"speed_mps": 2000.0},
            "formation": {
                "ideal_distance_m": 300.0,
                "speed_distance_slope": 0.01,
                "collision_avoidance_contribution_factor": 0.015,
            },
            # Orbit (see CapitalShipNavigator.orbit_target)
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

    # A guided missile has no tactician (it always engages the target given at
    # launch) and its navigator only does constant-angle pursuit, so only its
    # pilot is tuned. Its speed is constant, so the throttle gains are unused.
    MISSILE_DEFAULT = {
        "pilot": {
            "sample_time_s": 0.05,
            "minimum_throttle": 1.0,
            "yaw_kp": 3.0,
            "yaw_ki": 0.0,
            "yaw_kd": 0.0,
            "pitch_kp": -3.0,
            "pitch_ki": 0.0,
            "pitch_kd": 0.0,
            "roll_kp": -1.0,
            "roll_ki": 0.0,
            "roll_kd": 0.0,
            "throttle_kp": 0.0,
            "throttle_ki": 0.0,
            "throttle_kd": 0.0,
        },
    }
