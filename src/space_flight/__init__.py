import logging
import sys
from pathlib import Path

import numpy as np

from space_flight import _version

__version__ = _version.__version__

DATAFILES_PATH = Path(__file__).parent / "datafiles"
CONFIGURATION_PATH = Path(__file__).parent / "configuration"
DEFAULT_CONFIGURATION_PATH = DATAFILES_PATH / "default_configuration"
FIXTURES_PATH = Path(__file__).parent.parent.parent / "tests/fixtures"
CACHE_PATH = Path(__file__).parent.parent.parent / ".cache"

DEBUG_DELETION = False
DEBUG_COLLISION = False
DEBUG_HUD = False
RECORD_GAME = False
FLIGHT_MODEL = "airplane"  # "airplane", "space"
THROTTLE_BOOST_VALUE = 2.0  # Throttle command when boosting (1.0 is full thrust)

# Local warp (hyperspace jump in flight, see actors/warp_drive.py)
WARP_TUNNEL_OPACITY = 0.3  # Opacity of the hyperspace tunnel over the scene, 0..1
WARP_MAX_WHITEOUT = 0.0  # Strength of the white flashes entering/leaving, 0..1
# Cross-fades between the animation's phases. The tunnel starts fading in this
# long before the charge ends, so that it is fully there as the ship jumps
WARP_FADE_DURATION_S = 0.3
WARP_TURN_RATE_FACTOR = 0.1  # Turn rates cap while charging, warping, dropping out
WARP_CRUISE_THROTTLE = 0.5  # Throttle while charging, and after dropping out
# Warp speed: this many m/s per metre of altitude above the nearest body's ground,
# so the speed grows (and shrinks) exponentially with the distance to it. Keep
# WARP_SPEED_PER_ALTITUDE * WARP_RELAX_TIME_S under 0.25: the approach to a body
# then never overshoots into it.
WARP_SPEED_PER_ALTITUDE = 1.0  # 1/s
WARP_MIN_SPEED_MPS = 1000.0  # Floor of the warp speed near a body
WARP_MAX_SPEED_MPS = 5.0e6  # Ceiling of the warp speed, far from every body
WARP_SPACE_SPEED_MPS = 20000.0  # Warp speed in scenes without bodies
WARP_RELAX_TIME_S = 0.2  # Time constant of the ship's speed towards the warp speed
WARP_RELAX_MIN_FRAMES = 1.5  # ...stretched to this many frames at low frame rates
WARP_MIN_ALTITUDE_M = 10000.0  # A jump only starts above this altitude
WARP_AUTO_EXIT_ALTITUDE_M = 5000.0  # Drop out automatically below this altitude
# Wingmen dropping in after their leader's warp land this far from their slot at
# most, along each axis, as a fraction of the formation's slot spacing
WARP_ESCORT_SLOT_JITTER = 0.3
# A jump refused for want of altitude blinks the engine gauge this many times
WARP_REFUSED_BLINKS = 3
WARP_REFUSED_BLINK_PERIOD_S = 0.3

FORWARD_BODY = np.array([0.0, 1.0, 0.0])
RIGHT_BODY = np.array([1.0, 0.0, 0.0])
UP_BODY = np.array([0.0, 0.0, 1.0])
EPSILON_TOLERANCE = 1.0e-5
# The camera's far clip, in metres: clears the outermost cloud shell (512 km)
# and keeps the curved ocean horizon in view up to ~28 km of altitude. In
# flight the main camera only draws up to the depth split and a far camera the
# rest (see Scene.depth); the rear-view mirror and the ocean's
# reflection camera keep this whole range.
CAMERA_FAR_M = 600000.0

LOGGER = logging.getLogger()
LOGGER.handlers = []
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)


LOGGER.info(f"Importing space_flight {_version.__version__}")
