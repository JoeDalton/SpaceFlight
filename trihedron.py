import numpy as np
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    Geom,
    GeomLines,
    GeomNode,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
)


class Trihedron:
    """
    A class to display a trihedron, based on a parent Node

    It can be used either for debug or for a clearer visualization.
    """

    def __init__(self, app: ShowBase, parent):
        self.app = app
        geom = make_axes()
        node = GeomNode("axis")
        node.addGeom(geom)
        self.object = NodePath(node)
        self.object.setScale(10, 10, 10)
        self.object.reparentTo(parent)


def make_axes():
    """
    Defines the render of a trihedron
    """
    vformat = GeomVertexFormat.get_v3c4()
    vdata = GeomVertexData("vdata", vformat, Geom.UHStatic)
    vdata.uncleanSetNumRows(6)

    vertex = GeomVertexWriter(vdata, "vertex")
    color = GeomVertexWriter(vdata, "color")

    for x, y, z in np.eye(3):
        vertex.addData3(0, 0, 0)
        color.addData4(x, y, z, 1)
        vertex.addData3(x, y, z)
        color.addData4(x, y, z, 1)

    prim = GeomLines(Geom.UHStatic)
    prim.addNextVertices(6)

    geom = Geom(vdata)
    geom.addPrimitive(prim)
    return geom
