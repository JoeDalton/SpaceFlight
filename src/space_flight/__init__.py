import logging
import sys
from pathlib import Path

import numpy as np

# from space_flight import _version

# __version__ = _version.__version__

DATAFILES_PATH = Path(__file__).parent / "datafiles"
CONFIGURATION_PATH = Path(__file__).parent / "configuration"
FIXTURES_PATH = Path(__file__).parent.parent.parent / "tests/fixtures"

DEBUG_DELETION = False
DEBUG_COLLISION = False
RECORD_GAME = False
FLIGHT_MODEL = "airplane"  # "airplane", "space"

FORWARD_BODY = np.array([0.0, 1.0, 0.0])
RIGHT_BODY = np.array([1.0, 0.0, 0.0])
UP_BODY = np.array([0.0, 0.0, 1.0])
EPSILON_TOLERANCE = 1.0e-5

LOGGER = logging.getLogger()
LOGGER.handlers = []
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)

TARGET_FILTERS = [
    "All",
    "Enemies",
    "Capital ships",
    "Subsystems",
    "Turrets",
    "fighters",
    "",
    "",
]


LOGGER.info("Importing space_flight library")
# LOGGER.info(f"Importing space_flight {_version.__version__}")
