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

⚠️ ИДЕНТИФИКАТОР НАМЕРЕННО НЕ ЧИСЛОВОЙ.

Апстрим нумерует ревизии подряд: 0102, 0103, 0104… Если назвать нашу «0104»,
она столкнётся с апстримовской 0104 в следующем же релизе — два разных файла
с одинаковым revision id, и alembic не соберёт граф вообще. Префикс `as`
(airshadow) выводит наши миграции из его пространства имён навсегда.

⚠️ ПРИ СЛЕДУЮЩЕМ СИНКЕ АПСТРИМА БУДЕТ ДВЕ ГОЛОВЫ.

Как только апстрим добавит свою 0104, она и `as0001` обе ветвятся от 0103.
Бот запускает `command.upgrade(cfg, 'head')` — в ЕДИНСТВЕННОМ числе, поэтому
на двух головах он падает с «Multiple head revisions» и контейнер не стартует.

Лечится одной командой при синке, ДО деплоя:

    alembic merge -m "merge upstream <NNNN> with as0001" <NNNN> as0001

Она создаёт ревизию с `down_revision = ('<NNNN>', 'as0001')` и снова сводит
дерево к одной голове. Полная процедура — в инфраструктурной репе,
`.claude/commands/update-services.md`, раздел про синк.

🚫 НЕ «чинить» это перенаправлением `down_revision` нашей миграции на свежую
апстримовскую. На проде она уже применена и записана в `alembic_version`;
после перенаправления alembic посчитает апстримовские 0104…NNNN её предками,
решит, что они применены, и молча их пропустит — схема разъедется без единой
ошибки в логах.

Revision ID: as0001
Revises: 0103
"""

from alembic import op
import sqlalchemy as sa


revision = 'as0001'
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
        f'Миграция as0001 остановлена: в users есть {len(rows)} адрес(ов), '
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
