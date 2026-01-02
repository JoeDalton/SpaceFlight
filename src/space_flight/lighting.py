from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, DirectionalLight, Vec4
from typing import List


class Lighting:
    def __init__(
            self,
            app: ShowBase,
            directional_color: List = [1.0, 1.0, 0.9, 1],
            directional_direction: List = [-30, -60, 0],
            ambient_color: List = [0.1, 0.2, 0.4, 1],
        ):
        # Directional light
        dlight = DirectionalLight("dlight")
        dlight.set_color(Vec4(
            directional_color[0],
            directional_color[1],
            directional_color[2],
            directional_color[3],
        ))
        dlnp = app.render.attach_new_node(dlight)
        dlnp.set_hpr(
            directional_direction[0],
            directional_direction[1],
            directional_direction[2],
        )
        app.render.set_light(dlnp)

        # Ambient light
        alight = AmbientLight("alight")
        alight.set_color(Vec4(
            ambient_color[0],
            ambient_color[1],
            ambient_color[2],
            ambient_color[3],
        ))
        alnp = app.render.attach_new_node(alight)
        app.render.set_light(alnp)

        # # Use a 512x512 resolution shadow map
        # dlight.setShadowCaster(True, 512, 512)
        # # Enable the shader generator for the receiving nodes
        # app.render.setShaderAuto()
