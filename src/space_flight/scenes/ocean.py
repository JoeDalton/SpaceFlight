"""
The game's ocean: WorldBuilder's reflective ocean plus a collision plane.

The surface itself (mesh, swell, planar reflection, shaders) lives in
:mod:`world_builder.ocean`. This adds what only the game needs: the flat
terrain plane at Z=0 that ships crash into, and the material lasers read to
pick their spark colour.

Usage:
    from space_flight.scenes.ocean import Ocean
    self.ocean = Ocean(game=game)
"""

from __future__ import annotations

from world_builder.ocean import Ocean as WorldBuilderOcean

from space_flight.game.collisions import attach_collision_plane


class Ocean(WorldBuilderOcean):
    #: Terrain material, read at laser-hit time to pick a spark colour.
    material = "water"

    def __init__(self, game, *args, **kwargs):
        """
        :param game: The game instance.
        :param args: forwarded to :class:`world_builder.ocean.Ocean`
        :param kwargs: forwarded to :class:`world_builder.ocean.Ocean`
        """
        super().__init__(game, *args, **kwargs)
        # Flat at Z=0, like the reflection mirror: exact at the camera, where
        # the surface's curvature droop is zero.
        attach_collision_plane(
            game=self.game,
            name="terrain",
            collider_type="terrain",
            parent_node=self.base_node,
            parent_object=self,
        )
