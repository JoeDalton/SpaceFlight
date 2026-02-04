from typing import List

import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight import DISTANCE_TOLERANCE_M

INTERACT_MAX_DISTANCE_M = 2000.0

"""
Teams are defined as :
Neutral bystanders in team 0
Player in team 1 by default
Foes in any team > 1
"""


class Interactions:
    def __init__(
        self,
        app: ShowBase,
        actors: List = [],
    ):
        """
        A class for computing interactions between actors in the simulation

        :param app: The game object
        :param actors: A list containing all actors, defaults to []
        """
        self.app: ShowBase = app
        self.actors: List = actors
        self.n_actors: int = len(self.actors)

        self.directions: np.ndarray = np.zeros((self.n_actors, self.n_actors, 3))
        self.interact: np.ndarray = np.zeros((self.n_actors, self.n_actors), dtype=bool)
        self.distances: np.ndarray = np.zeros((self.n_actors, self.n_actors))
        self.alignments: np.ndarray = np.zeros((self.n_actors, self.n_actors))
        self.rel_velocities: np.ndarray = np.zeros((self.n_actors, self.n_actors, 3))

        self.app.taskMgr.add(self.interaction_update_task, "interactions_update")

    def add_actor(self, actor):
        """
        Adds an actor to the dict of interacting things and expands
        the interaction matrices

        :param actor: The actor to add
        """
        if actor in self.actors:
            raise ValueError(f"Actor {actor.name} is already in the actors' list")
        # Add actor to the team
        self.actors.append(actor)

        # Update the interaction matrix
        self.n_actors = len(self.actors)
        # Save old values
        old_directions = self.directions.copy()
        old_rel_velocities = self.rel_velocities.copy()
        old_interact = self.interact.copy()
        old_distances = self.distances.copy()
        old_alignments = self.alignments.copy()
        # Create new, bigger arrays
        self.directions = np.zeros((self.n_actors, self.n_actors, 3))
        self.rel_velocities = np.zeros((self.n_actors, self.n_actors, 3))
        self.interact = np.zeros((self.n_actors, self.n_actors), dtype=bool)
        self.distances = np.zeros((self.n_actors, self.n_actors))
        self.alignments = np.zeros((self.n_actors, self.n_actors))
        # Copy old values inside
        self.directions[: self.n_actors - 1, : self.n_actors - 1, :] = old_directions[
            :, :, :
        ]
        self.interact[: self.n_actors - 1, : self.n_actors - 1] = old_interact[:, :]
        self.distances[: self.n_actors - 1, : self.n_actors - 1] = old_distances[:, :]
        self.alignments[: self.n_actors - 1, : self.n_actors - 1] = old_alignments[:, :]
        self.rel_velocities[
            : self.n_actors - 1, : self.n_actors - 1, :
        ] = old_rel_velocities[:, :, :]

    def remove_actor(self, actor):
        """
        Removes an actor from the dict of interacting things and removes the
        corresponding lines and columns from the interaction matrices

        :param actor: The actor to remove
        """

        actor_index = self.get_actor_index(actor)

        # Remove actor from the list
        self.actors.pop(actor_index)

        # Remove the corresponding lines and columns in the interaction matrices
        self.n_actors = len(self.actors)
        self.directions = np.delete(
            np.delete(self.directions, actor_index, axis=0), actor_index, axis=1
        )
        self.interact = np.delete(
            np.delete(self.interact, actor_index, axis=0), actor_index, axis=1
        )
        self.distances = np.delete(
            np.delete(self.distances, actor_index, axis=0), actor_index, axis=1
        )
        self.alignments = np.delete(
            np.delete(self.alignments, actor_index, axis=0), actor_index, axis=1
        )
        self.rel_velocities = np.delete(
            np.delete(self.rel_velocities, actor_index, axis=0), actor_index, axis=1
        )

    def get_actor_index(self, actor) -> int:
        """
        Finds the actor's index in the list of actors

        :param actor: The actor to look up
        :return: Its index
        """
        actor_index = -1
        for idx in range(self.n_actors):
            if self.actors[idx] == actor:
                actor_index = idx
                break
        if actor_index == -1:
            raise ValueError(f"Actor {actor.name} is not in the actors' list")
        return actor_index

    def interaction_update_task(self, task):
        """
        Computes the interaction between actors

        TODO: Optimize this so every interaction is not computed at each step.
        The time between update should be:
            - proportional to distance between actors
            - inversely proportional to their closing speed
            - A bubble of a few seconds max
        """
        # Double loop over every actor, in the upper triangular quadrant
        for idx_source in range(1, self.n_actors):
            for idx_target in range(0, idx_source):
                # Identify actors
                source_actor = self.actors[idx_source]
                target_actor = self.actors[idx_target]

                # Find whether the two actors can interact based on teams
                # TODO: remove the both in same team condition if "protect" behaviour ?
                interact = not (
                    source_actor.team == 0  # Source is neutral
                    or target_actor.team == 0  # Target is neutral
                    or source_actor.team == target_actor.team  # Both in the same team
                )

                # Only compute the distance between actors if
                # they are a priori interactive
                if interact:
                    # Find relative positions and distance
                    direction = np.float64(
                        target_actor.position - source_actor.position
                    )
                    distance = np.linalg.norm(direction)
                    if distance > DISTANCE_TOLERANCE_M:
                        direction /= distance
                    else:
                        direction = np.zeros(3)
                        distance = 0.0
                    distance_interact = distance < INTERACT_MAX_DISTANCE_M
                    # Cancel interaction if they are too far apart
                    interact *= distance_interact

                if interact:
                    # Find relative velocity
                    try:
                        target_velocity = target_actor.speed
                    except AttributeError:
                        target_velocity = np.zeros(3)
                    try:
                        source_velocity = source_actor.speed
                    except AttributeError:
                        source_velocity = np.zeros(3)
                    rel_velocity = target_velocity - source_velocity

                    # Set array values
                    self.directions[idx_source, idx_target, :] = direction
                    self.distances[idx_source, idx_target] = distance
                    self.rel_velocities[idx_source, idx_target, :] = rel_velocity
                    # The inverse interaction follows directly
                    self.directions[idx_target, idx_source, :] = -direction
                    self.distances[idx_target, idx_source] = distance
                    self.rel_velocities[idx_target, idx_source, :] = -rel_velocity

                # Record interaction possibility
                self.interact[idx_source, idx_target] = interact
                self.interact[idx_target, idx_source] = interact

        # Full double loop for alignments (source -> target and target -> source)
        for idx_source in range(self.n_actors):
            for idx_target in range(self.n_actors):
                # Compute alignment only if there is an interaction
                if self.interact[idx_source, idx_target] and (idx_source != idx_target):
                    source_forward = self.actors[idx_source].forward
                    source_to_target_direction = self.directions[
                        idx_source, idx_target, :
                    ]
                    alignment = np.dot(source_to_target_direction, source_forward)
                    self.alignments[idx_source, idx_target] = alignment

        return task.cont
