"""Renewal of an EXPIRED trial must convert it in place (Базовый, same link),
not dead-end users into buying a brand-new subscription (new Remnawave user).

Root cause: the renewal resolver only auto-selects a single ACTIVE subscription,
so an expired trial returns None → «Продлить» silently returns → users fall back
to «Купить» → confirm_tariff_purchase → new sub + new link.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


async def test_handle_extend_falls_back_to_expired_trial(monkeypatch):
    from app.handlers.subscription import purchase

    monkeypatch.setattr(type(purchase.settings), 'is_multi_tariff_enabled', lambda self: True)
    monkeypatch.setattr(type(purchase.settings), 'is_tariffs_mode', lambda self: True)
    monkeypatch.setattr(purchase, '_resolve_subscription', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(
        'app.database.crud.subscription.get_active_subscriptions_by_user_id',
        AsyncMock(return_value=[]),
    )
    trial = SimpleNamespace(id=99, is_trial=True, tariff_id=3, status='expired')
    monkeypatch.setattr(
        'app.database.crud.subscription.get_renewable_trial_subscription',
        AsyncMock(return_value=trial),
    )
    show_extend = AsyncMock()
    monkeypatch.setattr('app.handlers.subscription.tariff_purchase.show_tariff_extend', show_extend)

    state = AsyncMock()
    callback = SimpleNamespace(
        data='subscription_extend',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    db_user = SimpleNamespace(id=7, language='ru', subscription=None)
    db = AsyncMock()

    await purchase.handle_extend_subscription(callback, db_user, db, state)

    state.update_data.assert_awaited_with(active_subscription_id=99)
    show_extend.assert_awaited_once()


async def test_handle_extend_no_fallback_when_active_sub_exists(monkeypatch):
    """If the user HAS an active sub, do not hijack into the trial — leave the
    existing behavior (resolver returned None for a multi-active picker case)."""
    from app.handlers.subscription import purchase

    monkeypatch.setattr(type(purchase.settings), 'is_multi_tariff_enabled', lambda self: True)
    monkeypatch.setattr(purchase, '_resolve_subscription', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(
        'app.database.crud.subscription.get_active_subscriptions_by_user_id',
        AsyncMock(return_value=[SimpleNamespace(id=1), SimpleNamespace(id=2)]),
    )
    trial_lookup = AsyncMock(return_value=SimpleNamespace(id=99, is_trial=True, tariff_id=3))
    monkeypatch.setattr('app.database.crud.subscription.get_renewable_trial_subscription', trial_lookup)
    show_extend = AsyncMock()
    monkeypatch.setattr('app.handlers.subscription.tariff_purchase.show_tariff_extend', show_extend)

    state = AsyncMock()
    callback = SimpleNamespace(
        data='subscription_extend',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    db_user = SimpleNamespace(id=7, language='ru', subscription=None)
    db = AsyncMock()

    await purchase.handle_extend_subscription(callback, db_user, db, state)

    trial_lookup.assert_not_awaited()
    show_extend.assert_not_awaited()


async def test_show_tariff_extend_resolves_expired_trial_via_fsm(monkeypatch):
    from app.handlers.subscription import tariff_purchase

    monkeypatch.setattr(type(tariff_purchase.settings), 'is_multi_tariff_enabled', lambda self: True)
    monkeypatch.setattr(tariff_purchase, 'get_active_subscriptions_by_user_id', AsyncMock(return_value=[]))
    trial = SimpleNamespace(id=99, is_trial=True, tariff_id=3, device_limit=1)
    resolve_by_id = AsyncMock(return_value=trial)
    monkeypatch.setattr(tariff_purchase, 'get_subscription_by_id_for_user', resolve_by_id)
    tariff = SimpleNamespace(id=3, name='Базовый', is_active=True, traffic_limit_gb=500, device_limit=5)
    monkeypatch.setattr(tariff_purchase, 'get_tariff_by_id', AsyncMock(return_value=tariff))
    monkeypatch.setattr(tariff_purchase, 'get_tariff_extend_keyboard', lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(tariff_purchase, 'format_traffic', lambda *a, **k: '500 ГБ')

    state = AsyncMock()
    state.get_data = AsyncMock(return_value={'active_subscription_id': 99})
    callback = SimpleNamespace(
        data='subscription_extend',
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )
    db_user = SimpleNamespace(
        id=7, language='ru', promo_group_id=None,
        get_primary_promo_group=lambda: None, promo_group=None,
    )
    db = AsyncMock()

    await tariff_purchase.show_tariff_extend(callback, db_user, db, state)

    # Resolved the expired trial via FSM and rendered the extend screen
    resolve_by_id.assert_awaited_with(db, 99, 7)
    callback.message.edit_text.assert_awaited()
