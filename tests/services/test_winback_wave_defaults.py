"""Pin the win-back expired-subscription discount wave defaults.

These are the automatic monitoring_service waves. The values ship in code (not a
persisted volume), so a redeploy resets the live config to exactly these — keeping
them here guards against an accidental silent revert to the old weak 10%/20%/24h.
"""

from __future__ import annotations

from pathlib import Path

from app.services.notification_settings_service import NotificationSettingsService as N


def test_default_constants_are_aggressive_winback():
    second = N._DEFAULTS['expired_second_wave']
    third = N._DEFAULTS['expired_third_wave']

    assert second['enabled'] is True
    assert second['discount_percent'] == 20
    assert second['valid_hours'] == 48

    assert third['enabled'] is True
    assert third['discount_percent'] == 35
    assert third['valid_hours'] == 72
    assert third['trigger_days'] == 5


def test_getters_return_new_defaults_on_fresh_state(tmp_path, monkeypatch):
    # Isolate from any real on-disk config so we exercise the defaults path.
    monkeypatch.setattr(N, '_storage_path', Path(tmp_path) / 'notification_settings.json')
    monkeypatch.setattr(N, '_data', {})
    monkeypatch.setattr(N, '_loaded', False)

    assert N.get_second_wave_discount_percent() == 20
    assert N.get_second_wave_valid_hours() == 48
    assert N.get_third_wave_discount_percent() == 35
    assert N.get_third_wave_valid_hours() == 72
    assert N.get_third_wave_trigger_days() == 5
