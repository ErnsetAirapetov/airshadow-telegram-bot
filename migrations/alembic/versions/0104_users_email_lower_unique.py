"""users.email — нормализация регистра + уникальный индекс по lower(email)

Закрывает класс бага, из-за которого покупка с лендинга заводила ВТОРОЙ аккаунт,
если клиент вписывал email в другом регистре (`Mail@x.ru` при существующем
`mail@x.ru`). Дальше весь email-контур кабинета — вход, регистрация,
восстановление пароля — отвечал HTTP 500 (MultipleResultsFound), потому что
ищет он через `func.lower(User.email)` и берёт `.scalar_one_or_none()`.

Разбор: docs/superpowers/specs/2026-08-10-bedolaga-email-case-duplicate-accounts.md

Индекс частичный — soft-deleted аккаунты исключены, иначе удалённый
пользователь навсегда занимал бы свой адрес и не смог бы зарегистрироваться
повторно.

Revision ID: 0104
Revises: 0103
"""

from alembic import op
import sqlalchemy as sa


revision = '0104'
down_revision = '0103'
branch_labels = None
depends_on = None

INDEX_NAME = 'uq_users_email_lower'

# Условие живой строки: непустой email у неудалённого пользователя.
_ALIVE = "email IS NOT NULL AND email <> '' AND status <> 'deleted'"

# Диагностический запрос — отдаём оператору в тексте ошибки, чтобы не искать.
_DUPLICATE_QUERY = f"""
SELECT lower(email) AS email_lc, count(*) AS cnt
FROM users
WHERE {_ALIVE}
GROUP BY lower(email)
HAVING count(*) > 1
"""


def _mask(email: str) -> str:
    """Не тащим полный адрес в лог миграции — хватает опознаваемого куска."""
    local, _, domain = (email or '').partition('@')
    head = local[:2] if len(local) > 2 else local
    return f'{head}***@{domain}' if domain else '***'


def _assert_no_case_duplicates(bind) -> None:
    """Падаем ДО бэкфилла и понятным текстом.

    Без этой проверки CREATE UNIQUE INDEX упал бы сырой ошибкой Postgres уже
    после того, как бэкфилл переписал часть адресов, — разбираться пришлось бы
    в наполовину применённом состоянии.
    """
    rows = bind.execute(sa.text(_DUPLICATE_QUERY)).fetchall()
    if not rows:
        return
    listed = ', '.join(f'{_mask(r[0])} ×{r[1]}' for r in rows[:10])
    more = f' и ещё {len(rows) - 10}' if len(rows) > 10 else ''
    raise RuntimeError(
        f'Миграция 0104 остановлена: в users есть {len(rows)} адрес(ов), '
        f'различающихся только регистром: {listed}{more}.\n'
        'Уникальный индекс по lower(email) их не примет. Сначала слейте дубли '
        'штатным app/services/account_merge_service.py::execute_merge '
        '(не правкой SQL — иначе разъедутся подписки и панель), затем повторите.\n'
        'Найти их полностью:\n' + _DUPLICATE_QUERY.strip()
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Проверка. Отдельным шагом, чтобы не оставить БД в полупропатченном виде.
    _assert_no_case_duplicates(bind)

    # 2. Бэкфилл: приводим уже записанные адреса к нижнему регистру.
    #    Трогаем и deleted-строки — иначе они разъедутся с новым инвариантом,
    #    а при восстановлении аккаунта снова родят коллизию.
    bind.execute(
        sa.text(
            "UPDATE users SET email = lower(email) "
            "WHERE email IS NOT NULL AND email <> '' AND email <> lower(email)"
        )
    )

    # 3. Индекс. Через raw SQL: функциональный + частичный индекс не выражается
    #    через op.create_index переносимо.
    bind.execute(sa.text(f'CREATE UNIQUE INDEX {INDEX_NAME} ON users (lower(email)) WHERE {_ALIVE}'))


def downgrade() -> None:
    # Бэкфилл необратим: исходный регистр адресов не сохранялся. Снимаем только
    # индекс — этого достаточно, чтобы откатить ограничение.
    op.get_bind().execute(sa.text(f'DROP INDEX IF EXISTS {INDEX_NAME}'))
