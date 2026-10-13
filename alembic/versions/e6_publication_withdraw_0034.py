"""Bounded terminal publication withdrawal, including previously full journals."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_publication_withdraw_0034'
down_revision = 'e6_deadline_clear_0033'
branch_labels = None
depends_on = None

TABLE = 'knowledge_publication_events'
CONSTRAINT = 'ck_knowledge_publication_revision'
NEW_CHECK = "revision BETWEEN 1 AND 251 AND (revision <= 250 OR action = 'withdraw')"


def _change(upgrade):
    check = NEW_CHECK if upgrade else 'revision BETWEEN 1 AND 250'
    if op.get_context().as_sql:
        if not upgrade or op.get_context().dialect.name != 'postgresql':
            raise RuntimeError('offline migration cannot verify publication history')
        op.execute('LOCK TABLE knowledge_publication_events IN ACCESS EXCLUSIVE MODE')
        op.drop_constraint(CONSTRAINT, TABLE, type_='check')
        op.create_check_constraint(CONSTRAINT, TABLE, check)
        return
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == 'postgresql':
        bind.execute(sa.text('LOCK TABLE knowledge_publication_events IN ACCESS EXCLUSIVE MODE'))
    elif dialect == 'sqlite':
        if bind.exec_driver_sql('PRAGMA foreign_keys').scalar():
            raise RuntimeError('publication migration requires a dedicated SQLite foreign_keys=OFF connection')
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            bind.exec_driver_sql('UPDATE knowledge_publication_events SET id = id WHERE 0')
        if bind.exec_driver_sql('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('publication migration requires intact foreign keys')
    else:
        raise RuntimeError('unsupported publication migration dialect')
    # Byte overflow may end below revision251; do not discard its recovery path
    # by installing an older reader over any populated history.
    if not upgrade and bind.scalar(sa.text('SELECT count(*) FROM knowledge_publication_events')):
        raise RuntimeError('preserve populated publication history and terminal withdrawals')
    if dialect == 'sqlite':
        with op.batch_alter_table(TABLE, recreate='always') as batch:
            batch.drop_constraint(CONSTRAINT, type_='check')
            batch.create_check_constraint(CONSTRAINT, check)
        if bind.exec_driver_sql('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('publication migration changed foreign key integrity')
    else:
        op.drop_constraint(CONSTRAINT, TABLE, type_='check')
        op.create_check_constraint(CONSTRAINT, TABLE, check)


def upgrade():
    _change(True)


def downgrade():
    _change(False)
