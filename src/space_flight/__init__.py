import logging
import sys
from pathlib import Path

import numpy as np
from world_builder import PLANET_RADIUS_M  # noqa: F401 - re-exported for the game

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

FORWARD_BODY = np.array([0.0, 1.0, 0.0])
RIGHT_BODY = np.array([1.0, 0.0, 0.0])
UP_BODY = np.array([0.0, 0.0, 1.0])
EPSILON_TOLERANCE = 1.0e-5
# The camera's far clip, in metres: clears the outermost cloud shell (512 km)
# and keeps the curved ocean horizon in view up to ~28 km of altitude. In
# flight the main camera only draws up to the depth split and a far camera the
# rest (see FlightState.split_depth); the rear-view mirror and the ocean's
# reflection camera keep this whole range.
CAMERA_FAR_M = 600000.0
# PLANET_RADIUS_M (imported above) is shared by the curved ocean and the cloud
# deck, both from WorldBuilder, which must droop identically.

LOGGER = logging.getLogger()
LOGGER.handlers = []
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)


LOGGER.info(f"Importing space_flight {_version.__version__}")
