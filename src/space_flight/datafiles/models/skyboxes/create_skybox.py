from direct.showbase.DirectObject import DirectObject
from direct.showbase.ShowBase import ShowBase
from panda3d.core import TexGenAttrib, TextureStage

"""
Create skyboxes with Spacescape

Rename files from right1-back6 to 0-5, then invert files 2 and 3 (top and bottom)

"""

skybox_name = "test"


class SkySphere(DirectObject):
    def __init__(self, base):
        self.sphere = base.loader.loadModel("InvertedSphere.egg")
        # Load a sphere with a radius of 1 unit and the faces directed inward.

        self.sphere.setTexGen(TextureStage.getDefault(), TexGenAttrib.MWorldPosition)
        self.sphere.setTexProjector(TextureStage.getDefault(), base.render, self.sphere)
        self.sphere.setTexPos(TextureStage.getDefault(), 0, 0, 0)
        self.sphere.setTexScale(TextureStage.getDefault(), 0.5)
        # Create some 3D texture coordinates on the sphere. For more info on this,
        # check the Panda3D manual.

        tex = base.loader.loadCubeMap(f"{skybox_name}_#.png")
        self.sphere.setTexture(tex)
        # Load the cube map and apply it to the sphere.

        self.sphere.setLightOff()
        # Tell the sphere to ignore the lighting.

        self.sphere.setScale(1000)
        # Increase the scale of the sphere so it will be larger than the scene.

        self.sphere.reparentTo(base.render)
        # Reparent the sphere to render so you can see it.

        result = self.sphere.writeBamFile(f"sky_{skybox_name}.bam")
        # Save out the bam file.
        print(result)
        # Print out whether the saving succeeded or not.


base = ShowBase()
my_sky_sphere = SkySphere(base=base)
base.run()
