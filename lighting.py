from direct.showbase.ShowBase import ShowBase
from panda3d.core import DirectionalLight, AmbientLight, Vec4


class Lighting():
    def __init__(self, app: ShowBase):
        # Directional light
        dlight = DirectionalLight("dlight")
        dlight.set_color(Vec4(1.0, 1.0, 0.9, 1))
        dlnp = app.render.attach_new_node(dlight)
        dlnp.set_hpr(-30, -60, 0)
        app.render.set_light(dlnp)

        # Ambient light
        alight = AmbientLight("alight")
        alight.set_color(Vec4(0.1, 0.2, 0.4, 1))
        alnp = app.render.attach_new_node(alight)
        app.render.set_light(alnp)