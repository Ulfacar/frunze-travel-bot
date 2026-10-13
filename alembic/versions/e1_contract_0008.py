"""E1-03: договор в услуге — реквизиты, подпись, сумма и ключ идемпотентности.

Аддитивная: только новые колонки в `service_cases` плюс уникальный частичный индекс
по ключу операции и проверка «есть сумма — есть валюта». Ни одной существующей
колонки не трогает, данные не переписывает.

Договор держится полями услуги, а не отдельной таблицей: техприложение ТЗ разрешает
это, пока не понадобится несколько договоров на одну услугу.

Значения направлений и прочие константы приложения сюда НЕ импортируются — ревизия
обязана оставаться снимком схемы на свою дату (урок ревизии e1_services_0007).

Revision ID: e1_contract_0008
Revises: e1_services_0007
Create Date: 2026-10-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1_contract_0008"
down_revision = "e1_services_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_cases", sa.Column("contract_reference", sa.String(128), nullable=True))
    op.add_column("service_cases", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service_cases", sa.Column("signed_by", sa.String(64), nullable=True))
    op.add_column("service_cases", sa.Column("agreed_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("service_cases", sa.Column("currency", sa.String(3), nullable=True))
    op.add_column("service_cases", sa.Column("amount_unknown_reason", sa.String(255), nullable=True))
    op.add_column("service_cases", sa.Column("idempotency_key", sa.String(128), nullable=True))
    # Частичный уникальный индекс: ключ не обязателен, а повтор с тем же ключом не
    # должен заводить вторую услугу (AC-01). Условие WHERE нужно для SQLite, где
    # NULL в уникальном индексе ведёт себя иначе, чем в PostgreSQL.
    op.create_index("uq_service_case_idempotency", "service_cases", ["idempotency_key"],
                    unique=True, sqlite_where=sa.text("idempotency_key IS NOT NULL"),
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    # Ограничение «есть сумма — есть валюта» добавляем только там, где СУБД умеет
    # ALTER ограничений. На PostgreSQL (боевая база) это обычный ALTER.
    #
    # На SQLite его пришлось бы ставить через batch_alter_table, а он пересоздаёт
    # таблицу копированием — и падает, когда на `service_cases` уже ссылается история
    # `service_events` при включённых внешних ключах. Проверяющая модель нашла это на
    # базе с данными. В тестах SQLite схему строит `create_all` из моделей, где
    # ограничение объявлено, так что покрытие не теряется.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite не умеет ALTER ограничений: batch_alter_table пересоздаёт таблицу
        # копированием и падает, когда на `service_cases` уже ссылается история
        # `service_events` при включённых внешних ключах. Снимаем проверку ссылок
        # на время пересоздания — данные при этом не меняются, копия полная.
        was_on = bool(bind.exec_driver_sql("PRAGMA foreign_keys").scalar())
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table("service_cases") as batch:
                batch.create_check_constraint(
                    "ck_service_case_amount_needs_currency",
                    "(agreed_amount IS NULL) OR"
                    " (currency IS NOT NULL AND length(trim(currency)) = 3)")
        finally:
            # Возвращаем ПРЕЖНЕЕ значение, а не включаем принудительно: если у
            # соединения проверка ссылок была выключена, миграция не должна её менять.
            bind.exec_driver_sql("PRAGMA foreign_keys=%s" % ("ON" if was_on else "OFF"))
    else:
        op.create_check_constraint(
            "ck_service_case_amount_needs_currency", "service_cases",
            "(agreed_amount IS NULL) OR (currency IS NOT NULL AND length(trim(currency)) = 3)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        was_on = bool(bind.exec_driver_sql("PRAGMA foreign_keys").scalar())
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table("service_cases") as batch:
                batch.drop_constraint("ck_service_case_amount_needs_currency", type_="check")
        finally:
            # Возвращаем ПРЕЖНЕЕ значение, а не включаем принудительно: если у
            # соединения проверка ссылок была выключена, миграция не должна её менять.
            bind.exec_driver_sql("PRAGMA foreign_keys=%s" % ("ON" if was_on else "OFF"))
    else:
        op.drop_constraint("ck_service_case_amount_needs_currency", "service_cases",
                           type_="check")
    op.drop_index("uq_service_case_idempotency", table_name="service_cases")
    for column in ("idempotency_key", "amount_unknown_reason", "currency",
                   "agreed_amount", "signed_by", "signed_at", "contract_reference"):
        op.drop_column("service_cases", column)
