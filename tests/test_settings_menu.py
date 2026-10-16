"""
Unit tests for the settings hub menu's navigation (mock app, no DirectGui).
"""

from unittest.mock import MagicMock

from space_flight.menus.settings_menu_state import SettingsMenuState


class TestSettingsHubNavigation:
    def test_gameplay_button_pushes_gameplay_state(self):
        app = MagicMock()
        hub = SettingsMenuState(app=app)

        hub.enter_gameplay_settings()

        app.state_manager.push.assert_called_once_with(
            app.state_manager.GAMEPLAY_SETTINGS_STATE
        )

    def test_input_button_pushes_input_state(self):
        s = SettingsMenuState(app=MagicMock())
        s.enter_input_settings()
        s.app.state_manager.push.assert_called_once_with(
            s.app.state_manager.INPUT_SETTINGS_STATE
        )

    def test_graphics_button_pushes_graphics_state(self):
        s = SettingsMenuState(app=MagicMock())
        s.enter_graphics_settings()
        s.app.state_manager.push.assert_called_once_with(
            s.app.state_manager.GRAPHICS_SETTINGS_STATE
        )

    def test_back_pops(self):
        s = SettingsMenuState(app=MagicMock())
        s.back()
        s.app.state_manager.pop.assert_called_once()
