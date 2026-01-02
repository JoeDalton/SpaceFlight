import logging
import sys
from pathlib import Path

# from space_flight import _version

# __version__ = _version.__version__

DATAFILES_PATH = Path(__file__).parent / "datafiles"
CONFIGURATION_PATH = Path(__file__).parent / "configuration"
FIXTURES_PATH = Path(__file__).parent.parent.parent / "tests/fixtures"

LOGGER = logging.getLogger()
LOGGER.handlers = []
LOGGER.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
LOGGER.addHandler(handler)

LOGGER.info("Importing space_flight library")
# LOGGER.info(f"Importing space_flight {_version.__version__}")
