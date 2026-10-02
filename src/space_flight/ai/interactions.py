from __future__ import annotations

from typing import Any, List
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

# Default speed/facing for actors without one; never written to.
_ZERO3 = np.zeros(3)
_ZERO3.flags.writeable = False


class Interactions:
    def __init__(self, max_actors: int = MAX_ACTORS):
        """
        A class for computing interactions between actors in the simulation.

        All interaction matrices are pre-allocated to max_actors * max_actors so that
        add_actor / remove_actor never trigger memory allocation during gameplay.
        Slot indices are stable for the lifetime of an actor: no index shift on removal.

        :param max_actors: Upper bound on the number of simultaneously live actors
        """
        self.max_actors = max_actors
        self.actors: List = [None] * max_actors  # sparse; None == empty slot
        self.actors_id_dict = {}  # UUID -> stable slot index
        self.alive = np.zeros(max_actors, dtype=bool)
        # LIFO stack of free slot indices; pop() is O(1)
        self.free_slots = list(range(max_actors - 1, -1, -1))

        self.directions: np.ndarray = np.zeros((max_actors, max_actors, 3))
        self.interact: np.ndarray = np.zeros((max_actors, max_actors), dtype=bool)
        self.distances: np.ndarray = np.zeros((max_actors, max_actors))
        self.alignments: np.ndarray = np.zeros((max_actors, max_actors))
        self.rel_velocities: np.ndarray = np.zeros((max_actors, max_actors, 3))
        # Where each live pair's results go in the matrices: for every pair of
        # live slots (i, j), the flat index i * max_actors + j into the
        # matrices viewed as one long row. update_interactions computes a
        # compact n_live x n_live block and scatters it through these indices
        # in one write per matrix. Only changes when an actor is added or
        # removed, so it is cached, and reset to None by add/remove_actor.
        self._live_pair_idx = None

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

    def add_actor(self, actor: Any):
        """
        Assigns actor to the next free slot without allocating new matrices.

        :param actor: The actor to add
        """
        if actor.id in self.actors_id_dict:
            raise ValueError(f"Actor {actor.name} is already in the actors' list")
        if not self.free_slots:
            raise RuntimeError(
                f"Cannot add actor: max_actors ({self.max_actors}) reached"
            )
        slot = self.free_slots.pop()
        self.actors[slot] = actor
        self.alive[slot] = True
        self.actors_id_dict[actor.id] = slot
        self._live_pair_idx = None

    def remove_actor(self, actor: Any):
        """
        Frees actor's slot and zeroes its rows/columns so stale values
        never leak into other actors' queries.

        :param actor: The actor to remove
        """
        slot = self.actors_id_dict.pop(actor.id)
        self.actors[slot] = None
        self.alive[slot] = False
        self._live_pair_idx = None

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

        self.free_slots.append(slot)

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

        Vectorized over every live pair at once. Distances, directions,
        relative velocities and alignments are refreshed for all live pairs,
        interacting or not; interact flags which pairs are hostile and in
        range. Matrices are written in place (callers hold views into them).

        Per-pair update scheduling by closing time (issue #19) is not worth it
        for this geometry: it costs about as much as recomputing everything.
        """
        live = np.flatnonzero(self.alive)
        if len(live) < 2:
            return

        actors = [self.actors[k] for k in live]
        positions = np.array([a.position for a in actors], dtype=float)
        # Some actors (e.g. subsystems) have no speed or facing: treat them as
        # static and unoriented so they still take part in interactions.
        velocities = np.array(
            [getattr(a, "speed", _ZERO3) for a in actors], dtype=float
        )
        forwards = np.array(
            [getattr(a, "forward", _ZERO3) for a in actors], dtype=float
        )
        teams = np.array([a.team for a in actors])

        # Explicit sums rather than einsum/linalg.norm: as fast, and
        # bit-identical to the scalar per-pair formulas.
        offsets = positions[None, :, :] - positions[:, None, :]  # [i, j] = P_j - P_i
        distances = np.sqrt(
            offsets[..., 0] * offsets[..., 0]
            + offsets[..., 1] * offsets[..., 1]
            + offsets[..., 2] * offsets[..., 2]
        )
        far = distances > TARGET_DISTANCE_TOLERANCE_M
        directions = offsets / np.where(far, distances, 1.0)[..., None]
        directions[~far] = 0.0
        distances[~far] = 0.0

        interact = (
            (teams[:, None] != teams[None, :])
            & (teams[:, None] != 0)
            & (teams[None, :] != 0)
            & (distances < INTERACT_MAX_DISTANCE_M)
        )
        alignments = (
            directions[..., 0] * forwards[:, None, 0]
            + directions[..., 1] * forwards[:, None, 1]
            + directions[..., 2] * forwards[:, None, 2]
        )
        rel_velocities = velocities[None, :, :] - velocities[:, None, :]

        # An actor never interacts with itself: keep the diagonal at zero even
        # when its own speed or facing is non-finite (NaN - NaN is NaN).
        diagonal = np.arange(len(live))
        interact[diagonal, diagonal] = False
        distances[diagonal, diagonal] = 0.0
        alignments[diagonal, diagonal] = 0.0
        directions[diagonal, diagonal] = 0.0  # whole [i, i, :] vector (3 coords)
        rel_velocities[diagonal, diagonal] = 0.0  # whole [i, i, :] vector (3 coords)

        flat = self._live_pair_indices(live)
        n_cells = self.max_actors * self.max_actors
        self.interact.reshape(n_cells)[flat] = interact.ravel()
        self.distances.reshape(n_cells)[flat] = distances.ravel()
        self.alignments.reshape(n_cells)[flat] = alignments.ravel()
        self.directions.reshape(n_cells, 3)[flat] = directions.reshape(-1, 3)
        self.rel_velocities.reshape(n_cells, 3)[flat] = rel_velocities.reshape(-1, 3)

    def _live_pair_indices(self, live: np.ndarray) -> np.ndarray:
        """
        Flat indices, into a (max_actors * max_actors) view of the matrices, of
        every (live, live) pair in row-major order. Cached until an actor is
        added or removed.

        :param live: Sorted slot indices of the live actors
        :return: The flat pair indices
        """
        if self._live_pair_idx is None:
            self._live_pair_idx = (
                live[:, None] * self.max_actors + live[None, :]
            ).ravel()
        return self._live_pair_idx

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
        self.free_slots = None

        self.directions = None
        self.interact = None
        self.distances = None
        self.alignments = None
        self.rel_velocities = None
        self._live_pair_idx = None
