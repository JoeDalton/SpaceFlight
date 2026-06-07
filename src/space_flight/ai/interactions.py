from typing import List
from uuid import UUID

import numpy as np

from space_flight.ai import INTERACT_MAX_DISTANCE_M, TARGET_DISTANCE_TOLERANCE_M

"""
Teams are defined as :
Neutral bystanders in team 0
Player in team 1 by default
Foes in any team > 1
"""

MAX_ACTORS = 64


class Interactions:
    def __init__(self, max_actors: int = MAX_ACTORS):
        """
        A class for computing interactions between actors in the simulation.

        All interaction matrices are pre-allocated to max_actors * max_actors so that
        add_actor / remove_actor never trigger memory allocation during gameplay.
        Slot indices are stable for the lifetime of an actor: no index shift on removal.

        :param max_actors: Upper bound on the number of simultaneously live actors
        """
        self._max_actors = max_actors
        self.actors: List = [None] * max_actors  # sparse; None == empty slot
        self.actors_id_dict = {}  # UUID -> stable slot index
        self.alive = np.zeros(max_actors, dtype=bool)
        # LIFO stack of free slot indices; pop() is O(1)
        self._free_slots = list(range(max_actors - 1, -1, -1))

        self.directions: np.ndarray = np.zeros((max_actors, max_actors, 3))
        self.interact: np.ndarray = np.zeros((max_actors, max_actors), dtype=bool)
        self.distances: np.ndarray = np.zeros((max_actors, max_actors))
        self.alignments: np.ndarray = np.zeros((max_actors, max_actors))
        self.rel_velocities: np.ndarray = np.zeros((max_actors, max_actors, 3))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def n_actors(self) -> int:
        return int(self.alive.sum())

    @property
    def live_actors(self) -> List:
        """Returns only the currently live actors (no None entries)."""
        return [self.actors[i] for i in np.where(self.alive)[0]]

    # ------------------------------------------------------------------
    # Actor management
    # ------------------------------------------------------------------

    def add_actor(self, actor):
        """
        Assigns actor to the next free slot without allocating new matrices.

        :param actor: The actor to add
        """
        if actor.id in self.actors_id_dict:
            raise ValueError(f"Actor {actor.name} is already in the actors' list")
        if not self._free_slots:
            raise RuntimeError(
                f"Cannot add actor: max_actors ({self._max_actors}) reached"
            )
        slot = self._free_slots.pop()
        self.actors[slot] = actor
        self.alive[slot] = True
        self.actors_id_dict[actor.id] = slot

    def remove_actor(self, actor):
        """
        Frees actor's slot and zeroes its rows/columns so stale values
        never leak into other actors' queries.

        :param actor: The actor to remove
        """
        slot = self.actors_id_dict.pop(actor.id)
        self.actors[slot] = None
        self.alive[slot] = False

        self.interact[slot, :] = False
        self.interact[:, slot] = False
        self.distances[slot, :] = 0.0
        self.distances[:, slot] = 0.0
        self.directions[slot, :, :] = 0.0
        self.directions[:, slot, :] = 0.0
        self.alignments[slot, :] = 0.0
        self.alignments[:, slot] = 0.0
        self.rel_velocities[slot, :, :] = 0.0
        self.rel_velocities[:, slot, :] = 0.0

        self._free_slots.append(slot)

    def get_actor_index_from_id(self, actor_id: UUID) -> int:
        """
        Returns the actor's stable slot index.

        :param actor_id: UUID of the actor to look up
        :return: Its slot index
        """
        try:
            return self.actors_id_dict[actor_id]
        except KeyError:
            raise ValueError(f"Actor {actor_id} is not in the actors' list")

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update_interactions(self):
        """
        Computes the interaction between actors.

        Iterates only live pairs, so the O(N²) cost is proportional to
        the number of live actors, not the pre-allocated capacity.

        TODO: Optimize this so every interaction is not computed at each step.
        The time between update should be:
            - proportional to distance between actors
            - inversely proportional to their closing speed
            - A bubble of a few seconds max
        TODO: add an "engagement" array to update these very frequently ?
        """
        live_indices = np.where(self.alive)[0]
        n_live = len(live_indices)

        # Upper-triangular pass: distances, directions, relative velocities
        for i in range(1, n_live):
            idx_source = live_indices[i]
            source_actor = self.actors[idx_source]
            for j in range(0, i):
                idx_target = live_indices[j]
                target_actor = self.actors[idx_target]

                interact = not (
                    source_actor.team == 0  # Source is neutral
                    or target_actor.team == 0  # Target is neutral
                    or source_actor.team == target_actor.team  # Same team
                )

                if interact:
                    direction = np.float64(
                        target_actor.position - source_actor.position
                    )
                    distance = np.linalg.norm(direction)
                    if distance > TARGET_DISTANCE_TOLERANCE_M:
                        direction /= distance
                    else:
                        direction = np.zeros(3)
                        distance = 0.0
                    distance_interact = distance < INTERACT_MAX_DISTANCE_M
                    interact *= distance_interact

                if interact:
                    try:
                        target_velocity = target_actor.speed
                    except AttributeError:
                        target_velocity = np.zeros(3)
                    try:
                        source_velocity = source_actor.speed
                    except AttributeError:
                        source_velocity = np.zeros(3)
                    rel_velocity = target_velocity - source_velocity

                    self.directions[idx_source, idx_target, :] = direction
                    self.distances[idx_source, idx_target] = distance
                    self.rel_velocities[idx_source, idx_target, :] = rel_velocity
                    self.directions[idx_target, idx_source, :] = -direction
                    self.distances[idx_target, idx_source] = distance
                    self.rel_velocities[idx_target, idx_source, :] = -rel_velocity

                self.interact[idx_source, idx_target] = interact
                self.interact[idx_target, idx_source] = interact

        # Full pass for alignments (source -> target and target -> source)
        for i in range(n_live):
            idx_source = live_indices[i]
            source_forward = self.actors[idx_source].forward
            for j in range(n_live):
                idx_target = live_indices[j]
                if self.interact[idx_source, idx_target] and (idx_source != idx_target):
                    source_to_target_direction = self.directions[
                        idx_source, idx_target, :
                    ]
                    alignment = np.dot(source_to_target_direction, source_forward)
                    self.alignments[idx_source, idx_target] = alignment

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def clean(self):
        """
        Cleans the Interactions object
        """
        self.actors = None
        self.actors_id_dict = None
        self.alive = None
        self._free_slots = None

        self.directions = None
        self.interact = None
        self.distances = None
        self.alignments = None
        self.rel_velocities = None
