from typing import List

import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight import DISTANCE_TOLERANCE_M

"""
Teams are defined as :
Neutral bystanders in team 0
Player in team 1
Foes in any team > 1

TODO: teams in actors, not in here ? It would simplify things and allow using a list
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
        self.distances: np.ndarray = np.zeros((self.n_actors, self.n_actors))
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
        old_distances = self.distances.copy()
        # Create new, bigger arrays
        self.directions = np.zeros((self.n_actors, self.n_actors, 3))
        self.rel_velocities = np.zeros((self.n_actors, self.n_actors, 3))
        self.distances = np.zeros((self.n_actors, self.n_actors))
        # Copy old values inside
        self.directions[: self.n_actors - 1, : self.n_actors - 1, :] = old_directions[
            :, :, :
        ]
        self.distances[: self.n_actors - 1, : self.n_actors - 1] = old_distances[:, :]
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
        self.distances = np.delete(
            np.delete(self.distances, actor_index, axis=0), actor_index, axis=1
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

        TODO: Between all actors if I use this for collision avoidance

        TODO: Optimize this so every interaction is not computed at each step.
        The time between update should be:
            - proportional to distance between actors
            - inversely proportional to their relative speed
        """
        # Double loop over every actor, in the upper triangular quadrant
        for idx_source in range(1, self.n_actors):
            for idx_target in range(0, idx_source):
                # Identify actors
                source_actor = self.actors[idx_source]
                target_actor = self.actors[idx_target]

                # Only compute the interaction if the actors are on adverse teams
                if not (
                    source_actor.team == 0  # Source is neutral
                    or target_actor.team == 0  # Target is neutral
                    or source_actor.team == target_actor.team  # Both in the same team
                ):
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
        return task.cont
