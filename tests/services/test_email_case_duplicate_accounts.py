"""Регрессия: регистр email плодил дубли аккаунтов и ронял вход в кабинет (HTTP 500).

Разбор инцидента: docs/superpowers/specs/2026-08-10-bedolaga-email-case-duplicate-accounts.md
(репозиторий инфраструктуры Air-Shadow).

Что было
────────
Покупка с лендинга искала пользователя ТОЧНЫМ сравнением ``User.email ==``,
а весь остальной кабинет — через ``func.lower(User.email)``. Клиент,
зарегистрированный как ``mail@x.ru``, при покупке с ``Mail@x.ru`` получал
ВТОРОЙ аккаунт с новым паролем. После этого любой email-роут кабинета брал
результат через ``.scalar_one_or_none()`` и падал с ``MultipleResultsFound``
→ FastAPI отдавал 500. Пароль при этом был верным — до его проверки код не
доходил, и совет «сбросьте пароль» не помогал: восстановление падало так же.

Покрытые случаи
───────────────
1. Нормализация на входе: ``PurchaseRequest`` приводит email к нижнему регистру
   (и получателя подарка тоже), telegram-username не трогает.
2. ``_find_or_create_user`` переиспользует существующий аккаунт при отличающемся
   регистре и НЕ создаёт вторую строку.
3. ``_find_or_create_user`` пишет новый email в нижнем регистре.
4. ``_find_or_create_user`` не воскрешает soft-deleted аккаунт (побочная находка A).
5. ``get_user_by_email`` на паре строк, различающихся регистром, возвращает
   основной аккаунт и НЕ бросает MultipleResultsFound.
6. ``is_email_taken`` в тех же условиях отвечает True, а не падает.

Случаи 5-6 — это тот самый общий код, из-за которого 500 отдавали вход,
регистрация и восстановление пароля; роуты в ``app/cabinet/routes/auth.py``
поправлены тем же приёмом (``.order_by(User.id)`` + ``.scalars().first()``).

Барьер уровня БД — частичный уникальный индекс по ``lower(email)`` — стоит в
миграции ``0104_users_email_lower_unique``; здесь он не воспроизводится, потому
что тесты создают таблицы через ``create_all``, а не прогоном alembic.
"""

from __future__ import annotations

import pytest

from app.cabinet.routes.landing import PurchaseRequest
from app.database.crud.user import get_user_by_email, is_email_taken
from app.database.models import PromoGroup, User, UserStatus
from tests.fixtures.sqlite_memory import memory_session

EXISTING = 'client@example.com'
MIXED_CASE = 'Client@Example.com'


def _purchase_payload(**overrides):
    payload = {
        'tariff_id': 1,
        'period_days': 30,
        'contact_type': 'email',
        'contact_value': MIXED_CASE,
        'payment_method': 'platega',
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────────────────────────
# 1. Нормализация на входе
# ──────────────────────────────────────────────────────────────────────────────


def test_purchase_request_lowercases_email():
    """Email из тела запроса лендинга больше не попадает в users.email как есть."""
    assert PurchaseRequest(**_purchase_payload()).contact_value == EXISTING


def test_purchase_request_strips_whitespace():
    """Ведущие/хвостовые пробелы из формы не создают ещё один вариант адреса."""
    req = PurchaseRequest(**_purchase_payload(contact_value=f'  {MIXED_CASE}  '))
    assert req.contact_value == EXISTING


def test_purchase_request_normalizes_gift_recipient_email():
    """Получатель подарка — та же точка входа в users, нормализуем и его."""
    req = PurchaseRequest(
        **_purchase_payload(
            is_gift=True,
            gift_recipient_type='email',
            gift_recipient_value='Friend@Example.COM',
        )
    )
    assert req.gift_recipient_value == 'friend@example.com'


def test_purchase_request_keeps_telegram_username_case():
    """Telegram-username регистр не меняем: он не ключ поиска пользователя."""
    req = PurchaseRequest(
        **_purchase_payload(contact_type='telegram', contact_value='@SomeUser')
    )
    assert req.contact_value == '@SomeUser'


# ──────────────────────────────────────────────────────────────────────────────
# 2-4. _find_or_create_user на реальных запросах к БД
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _patch_user_deps(monkeypatch):
    """Отвязываем создание пользователя от промо-групп и реферальных кодов.

    Нас интересует ровно поиск по email; промо-группа и referral_code — соседние
    зависимости, которые тянут свои таблицы и уводят тест от предмета.
    """
    import app.services.guest_purchase_service as gps

    class _Group:
        id = 1

    async def _fake_group(_db):
        return _Group()

    async def _fake_code(_db):
        return 'refTEST01'

    monkeypatch.setattr(gps, '_get_or_create_default_promo_group', _fake_group)
    monkeypatch.setattr(gps, 'create_unique_referral_code', _fake_code)
    return gps


async def _count_users(db) -> int:
    from sqlalchemy import func, select

    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


@pytest.mark.asyncio
async def test_reuses_account_when_case_differs(monkeypatch, _patch_user_deps):
    """Главный кейс: покупка с `Client@Example.com` находит `client@example.com`."""
    gps = _patch_user_deps
    async with memory_session(monkeypatch, [User.__table__, PromoGroup.__table__]) as db:
        db.add(
            User(
                auth_type='email',
                email=EXISTING,
                email_verified=True,
                password_hash='x',
                promo_group_id=1,
                referral_code='refEXIST',
                status=UserStatus.ACTIVE.value,
            )
        )
        await db.commit()

        user, is_new = await gps._find_or_create_user(db, 'email', MIXED_CASE)

        assert user.email == EXISTING, 'должен вернуться существующий аккаунт'
        assert is_new is False, 'пароль не перевыпускается — аккаунт не новый'
        assert await _count_users(db) == 1, 'вторая строка создаваться не должна'


@pytest.mark.asyncio
async def test_new_user_is_stored_lowercase(monkeypatch, _patch_user_deps):
    """Новый аккаунт пишется в нижнем регистре — иначе мина взведётся заново."""
    gps = _patch_user_deps
    async with memory_session(monkeypatch, [User.__table__, PromoGroup.__table__]) as db:
        user, is_new = await gps._find_or_create_user(db, 'email', MIXED_CASE)

        assert user.email == EXISTING
        assert is_new is True
        assert await _count_users(db) == 1


@pytest.mark.asyncio
async def test_deleted_account_is_reactivated_not_duplicated(monkeypatch, _patch_user_deps):
    """Побочная находка A: вернувшийся клиент получает РАБОЧИЙ аккаунт.

    Вторую строку с тем же адресом создать нельзя — на users.email стоит UNIQUE,
    INSERT упал бы IntegrityError'ом и покупка вернула бы 500. Поэтому запись
    переиспользуется, но обязательно с переводом в ACTIVE: раньше она «оживала»
    со status='deleted', и вход после оплаты отдавал 401 «Invalid email or
    password» — клиент платил и не мог войти.
    """
    gps = _patch_user_deps
    async with memory_session(monkeypatch, [User.__table__, PromoGroup.__table__]) as db:
        db.add(
            User(
                auth_type='email',
                email=EXISTING,
                password_hash='old-hash',
                promo_group_id=1,
                referral_code='refDEL',
                status=UserStatus.DELETED.value,
            )
        )
        await db.commit()

        user, is_new = await gps._find_or_create_user(db, 'email', MIXED_CASE)

        assert await _count_users(db) == 1, 'вторая строка невозможна: UNIQUE на email'
        assert user.status == UserStatus.ACTIVE.value, 'иначе вход отдаст 401 после оплаты'
        assert is_new is True, 'выдан новый пароль — клиент получит его письмом'
        assert user.password_hash != 'old-hash'
        assert user.email == EXISTING


# ──────────────────────────────────────────────────────────────────────────────
# 5-6. Чтения устойчивы к уже существующим дублям (то, что отдавало 500)
# ──────────────────────────────────────────────────────────────────────────────


async def _seed_case_duplicates(db) -> None:
    """Пара строк, различающихся только регистром, — как было на проде.

    Уникальность в модели стоит на `email` как есть, поэтому СУБД такую пару
    пропускала. Ровно это и не давало создать уникальный индекс по lower(email)
    без предварительной расчистки.
    """
    db.add_all(
        [
            User(
                auth_type='yandex',
                email=EXISTING,
                promo_group_id=1,
                referral_code='refLOWER',
                status=UserStatus.ACTIVE.value,
            ),
            User(
                auth_type='email',
                email=MIXED_CASE,
                password_hash='x',
                promo_group_id=1,
                referral_code='refUPPER',
                status=UserStatus.ACTIVE.value,
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_get_user_by_email_survives_duplicates(monkeypatch):
    """Раньше здесь вылетал MultipleResultsFound → 500 во всём email-контуре."""
    async with memory_session(monkeypatch, [User.__table__, PromoGroup.__table__]) as db:
        await _seed_case_duplicates(db)

        user = await get_user_by_email(db, MIXED_CASE)

        assert user is not None
        assert user.email == EXISTING, 'детерминированно берём самый старый аккаунт'


@pytest.mark.asyncio
async def test_is_email_taken_survives_duplicates(monkeypatch):
    """Проверка занятости адреса тоже падала на дубле — теперь честный True."""
    async with memory_session(monkeypatch, [User.__table__, PromoGroup.__table__]) as db:
        await _seed_case_duplicates(db)

        assert await is_email_taken(db, MIXED_CASE) is True
        assert await is_email_taken(db, 'nobody@example.com') is False
