"""Reserve one terminal deadline withdrawal; preserve existing journal receipts."""
import sqlalchemy as sa
from alembic import op

revision = "e6_deadline_clear_0033"
down_revision = "e6_notification_drafts_0032"
branch_labels = None
depends_on = None

TABLE = "entry_deadline_revisions"
CONSTRAINT = "ck_entry_deadline_revision"


def _change(limit):
    if op.get_context().as_sql:
        if limit != 251 or op.get_context().dialect.name != "postgresql":
            raise RuntimeError("offline migration cannot verify deadline history and foreign keys")
        op.execute("LOCK TABLE entry_deadline_revisions IN ACCESS EXCLUSIVE MODE")
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")
        op.create_check_constraint(CONSTRAINT, TABLE, "revision BETWEEN 1 AND 251")
        return
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(sa.text("LOCK TABLE entry_deadline_revisions IN ACCESS EXCLUSIVE MODE"))
    elif dialect == "sqlite":
        # Rebuild only on the dedicated migration connection, never by turning
        # FK enforcement off inside an existing transaction (a SQLite no-op).
        if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
            raise RuntimeError("deadline constraint migration requires a dedicated SQLite foreign_keys=OFF connection")
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            bind.exec_driver_sql("UPDATE entry_deadline_revisions SET id = id WHERE 0")
        if bind.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("deadline migration requires intact foreign keys")
    else:
        raise RuntimeError("unsupported deadline constraint migration dialect")
    # A byte-cap terminal clear may be below revision251. Conservatively retain
    # all populated journals instead of duplicating runtime canonical accounting
    # in this historical migration or enabling rollback to an incompatible reader.
    if limit == 250 and bind.scalar(sa.text("SELECT count(*) FROM entry_deadline_revisions")):
        raise RuntimeError("preserve populated deadline history and terminal withdrawals")
    if dialect == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT, type_="check")
            batch.create_check_constraint(CONSTRAINT, f"revision BETWEEN 1 AND {limit}")
        if bind.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("deadline migration changed foreign key integrity")
    else:
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")
        op.create_check_constraint(CONSTRAINT, TABLE, f"revision BETWEEN 1 AND {limit}")


def upgrade():
    _change(251)


def downgrade():
    _change(250)
