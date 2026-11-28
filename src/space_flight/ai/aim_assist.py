"""
Generic aim assist: where to throw something at a target, within a cone around
the launcher's own axis.

Shared by the laser cannons (:class:`~space_flight.ai.auto_aim.AutoAim`, axis =
the nose) and the bomb launchers (axis = the launch direction): the lead
(where the target will be after the projectile's time of flight) and the cone
the aim is bent within are the same.
"""

from __future__ import annotations

import numpy as np

from space_flight.ai.interactions import Interactions, pair_geometry
from space_flight.utils import magnitude

# Below this, a vector is taken for null
_EPSILON = 1e-4


class AssistCone:
    """
    The cone around an axis within which an aim may be bent: it stays as asked
    inside it, and is clamped onto its surface (same lateral direction) outside.
    """

    def __init__(self, max_angle_deg: float):
        """
        :param max_angle_deg: The cone's half-angle
        """
        self.max_angle_rad = np.deg2rad(max_angle_deg)
        self.min_alignment = np.cos(self.max_angle_rad)

    def contains(self, direction: np.ndarray, axis: np.ndarray) -> bool:
        """
        :param direction: A unit direction
        :param axis: The cone's unit axis
        :return: Whether the direction lies within the cone
        """
        return bool(np.dot(direction, axis) >= self.min_alignment)

    def clamp(self, direction: np.ndarray, axis: np.ndarray) -> np.ndarray:
        """
        :param direction: A unit direction
        :param axis: The cone's unit axis
        :return: The direction itself within the cone, else the one on the
            cone's surface with the same lateral direction (the component
            across the axis), normalised
        """
        if self.contains(direction, axis):
            return np.asarray(direction, dtype=float)
        lateral = direction - np.dot(direction, axis) * axis
        lateral_amplitude = magnitude(lateral)
        if lateral_amplitude < _EPSILON:
            # Straight behind the axis: any lateral direction will do, there is
            # none to keep
            return np.array(axis, dtype=float)
        return (
            np.cos(self.max_angle_rad) * axis
            + np.sin(self.max_angle_rad) * lateral / lateral_amplitude
        )


def target_kinematics(
    interactions: Interactions,
    actor_id,
    actor_position: np.ndarray,
    target_id,
    projectile_speed_mps: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """
    :param interactions: The game's interactions
    :param actor_id: The shooter's id
    :param actor_position: The shooter's world position
    :param target_id: Its target's id
    :param projectile_speed_mps: The projectile's speed relative to the shooter
        (projectiles inherit the shooter's velocity)
    :return: The target's current position, and its raw lead offset: how far it
        moves, relative to the shooter, during the projectile's time of flight
        (taken as the distance over the speed). None if the shooter has no
        target in the interactions, or has itself gone.
    """
    if target_id is None:
        return None
    try:
        geometry = pair_geometry(interactions, actor_id, target_id)
    except ValueError:
        # The shooter has died during this frame
        return None
    if geometry is None:
        # No target
        return None
    distance_m, direction, relative_speed_vector = geometry
    flight_time_s = distance_m / projectile_speed_mps
    return (
        actor_position + distance_m * direction,
        relative_speed_vector * flight_time_s,
    )


def exact_target_kinematics(
    interactions: Interactions,
    actor_id,
    actor_position: np.ndarray,
    target_id,
    projectile_speed_mps: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """
    NOT USED YET: an exact alternative to :func:`target_kinematics`, kept (and
    tested) for the day the first-order lead proves too coarse, e.g. for slow
    projectiles such as bombs against a target moving across the shooter's
    frame. Swapping it in changes the lasers' lead slightly, hence the
    auto-aim tests' expected values; nothing calls it today.

    Same inputs and outputs as :func:`target_kinematics`, but the flight time is
    solved exactly instead of being taken as distance / speed, i.e. as if the
    target stood still during the flight. In the shooter's frame (the shooter
    at rest, the projectile flying at its speed s along the unit direction d)
    the target, at relative position r with relative velocity w, is hit at the
    time t that satisfies r + w t = s t d. Taking the squared length of both
    sides eliminates d::

        (w.w - s^2) t^2 + 2 (r.w) t + r.r = 0

    The earliest positive root is the flight time. The lead offset is then
    ``w t``, which makes ``target position + lead`` the exact meeting point.

    :param interactions: The game's interactions
    :param actor_id: The shooter's id
    :param actor_position: The shooter's world position
    :param target_id: Its target's id
    :param projectile_speed_mps: The projectile's speed relative to the shooter
    :return: The target's current position, and its lead offset (how far it
        moves, relative to the shooter, during the exact flight time). None if
        there is no target in the interactions, or the shooter has gone, or no
        intercept exists (the target outruns the projectile, or is already on
        the shooter).
    """
    if target_id is None:
        return None
    try:
        geometry = pair_geometry(interactions, actor_id, target_id)
    except ValueError:
        return None
    if geometry is None:
        return None
    distance_m, direction, relative_velocity = geometry
    relative_position = distance_m * direction
    a = float(relative_velocity @ relative_velocity) - projectile_speed_mps**2
    b = 2.0 * float(relative_position @ relative_velocity)
    c = float(relative_position @ relative_position)
    if c < _EPSILON**2 or projectile_speed_mps <= 0.0:
        return None
    if abs(a) < 1e-9:
        # The target is as fast as the projectile: the equation is linear, and
        # has a positive root only if the target is closing in
        if b >= 0.0:
            return None
        flight_time_s = -c / b
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant < 0.0:
            return None
        root = np.sqrt(discriminant)
        times_s = [
            t for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)) if t > 0.0
        ]
        if not times_s:
            return None
        flight_time_s = min(times_s)
    return actor_position + relative_position, relative_velocity * flight_time_s


def aim_toward(
    cone: AssistCone,
    axis: np.ndarray,
    start_position: np.ndarray,
    aim_point: np.ndarray,
) -> tuple[np.ndarray, bool]:
    """
    :param cone: The cone the aim may be bent within
    :param axis: The cone's unit axis (the direction fired when there is nothing
        to aim at)
    :param start_position: Where the projectile starts
    :param aim_point: The point to hit (the target's lead position)
    :return: The unit direction to fire, in the cone, and whether the aim point
        was in the cone itself (else the direction is clamped onto its surface)
    """
    to_point = aim_point - start_position
    norm = magnitude(to_point)
    if norm < _EPSILON:
        # Better safe than sorry
        return np.array(axis, dtype=float), True
    desired = to_point / norm
    return cone.clamp(desired, axis), cone.contains(desired, axis)
