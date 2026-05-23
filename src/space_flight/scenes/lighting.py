from typing import List

from panda3d.core import AmbientLight, DirectionalLight, Point3, Vec4


class Lighting:
    def __init__(
        self,
        game,
        directional_color: List = [0.5, 0.5, 0.45, 1],
        directional_direction: List = [-30, -60, 0],  # FROM scene TOWARD sun
        ambient_color: List = [0.1, 0.2, 0.4, 1],
    ):
        self.game = game
        # Directional light
        self.dlight = DirectionalLight("dlight")
        self.dlight.set_color(
            Vec4(
                directional_color[0],
                directional_color[1],
                directional_color[2],
                directional_color[3],
            )
        )
        self.dlnp = game.root_node.attach_new_node(self.dlight)
        self.dlnp.look_at(
            Point3(
                -directional_direction[0],
                -directional_direction[1],
                -directional_direction[2],
            )
        )
        game.app.render.set_light(self.dlnp)

        # Ambient light
        self.alight = AmbientLight("alight")
        self.alight.set_color(
            Vec4(
                ambient_color[0],
                ambient_color[1],
                ambient_color[2],
                ambient_color[3],
            )
        )
        self.alnp = game.root_node.attach_new_node(self.alight)
        game.app.render.set_light(self.alnp)

        # # Use a 512x512 resolution shadow map
        # dlight.setShadowCaster(True, 512, 512)
        # # Enable the shader generator for the receiving nodes
        # game.app.render.setShaderAuto()

    def clean(self):
        """
        Cleans the lighting object
        """
        # Clean directional light
        self.game.app.render.clear_light(self.dlnp)
        self.dlnp.removeNode()
        self.dlight = None
        # Clean ambient light
        self.game.app.render.clear_light(self.alnp)
        self.alnp.removeNode()
        self.alight = None

        self.game = None
