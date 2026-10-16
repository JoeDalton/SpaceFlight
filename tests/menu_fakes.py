"""
Stand-ins for the menu widgets, shared by the settings menu tests.
"""

from unittest.mock import MagicMock


def mock_slider(value):
    """A stand-in CustomSlider exposing get_value()."""
    slider = MagicMock()
    slider.get_value.return_value = value
    return slider
