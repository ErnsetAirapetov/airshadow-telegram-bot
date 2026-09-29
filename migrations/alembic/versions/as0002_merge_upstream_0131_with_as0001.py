"""merge upstream 0131 with as0001

Сводит две головы: апстримовскую цепочку 0104…0131 (ветвится от 0103) и нашу
as0001 (уникальный индекс по lower(email), тоже от 0103). Бот зовёт
upgrade('head') в единственном числе и на двух головах не стартует.

down_revision as0001 намеренно НЕ переносится на свежую апстримовскую ревизию:
на проде as0001 уже записана в alembic_version, и перенос заставил бы alembic
молча пропустить 0104…0131.

Revision ID: as0002
Revises: 0131, as0001
"""

revision = 'as0002'
down_revision = ('0131', 'as0001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
