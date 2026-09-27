from pathlib import Path

from direct.showbase.DirectObject import DirectObject
from direct.showbase.ShowBase import ShowBase
from panda3d.core import Filename, TexGenAttrib, TextureStage

"""
Create skyboxes with Spacescape

Rename files from right1-back6 to 0-5, then invert files 2 and 3 (top and bottom).
Can be launched from any directory; the bam file is written next to this script.

The cube map is deliberately NOT stored in the bam: Panda3D resolves a "#" texture
pattern only against the current working directory, so a baked-in path breaks as
soon as the game is launched from elsewhere (e.g. the MS_Windows_install scripts).
Skybox applies the cube map at runtime from an absolute path instead.
"""

skybox_name = "dusk"
SKYBOX_DIR = Path(__file__).resolve().parent


class SkySphere(DirectObject):
    def __init__(self, base):
        self.sphere = base.loader.loadModel(
            Filename.fromOsSpecific(str(SKYBOX_DIR / "InvertedSphere.egg"))
        )
        # Load a sphere with a radius of 1 unit and the faces directed inward.

        self.sphere.setTexGen(TextureStage.getDefault(), TexGenAttrib.MWorldPosition)
        self.sphere.setTexProjector(TextureStage.getDefault(), base.render, self.sphere)
        self.sphere.setTexPos(TextureStage.getDefault(), 0, 0, 0)
        self.sphere.setTexScale(TextureStage.getDefault(), 0.5)
        # Create some 3D texture coordinates on the sphere. For more info on this,
        # check the Panda3D manual.

        self.sphere.setLightOff()
        # Tell the sphere to ignore the lighting.

        if skybox_name == "dusk":
            ts = TextureStage.getDefault()
            self.sphere.setTexHpr(ts, (0, 90, 0))
        # Turn texture map if necessary

        self.sphere.setScale(1000)

        result = self.sphere.writeBamFile(
            Filename.fromOsSpecific(str(SKYBOX_DIR / f"{skybox_name}.bam"))
        )
        # Save out the bam file, without the cube map (see module docstring).
        print(result)

        tex = base.loader.loadCubeMap(
            Filename.fromOsSpecific(str(SKYBOX_DIR / f"{skybox_name}_#.png"))
        )
        self.sphere.setTexture(tex)
        # Apply the cube map for the preview only.

        self.sphere.reparentTo(base.render)


base = ShowBase()
my_sky_sphere = SkySphere(base=base)
base.run()
