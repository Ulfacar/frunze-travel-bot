"""SQL роли `frunze_crm` в БД бота (B1, предаудит B7): ровно нужные права и ничего сверх."""
import re

import pytest

from scripts.crm_bot_role import ROLE, WRITE_TABLES, role_sql

PASSWORD = 'S' * 40


def test_write_grants_are_exactly_the_route_tables():
    sql = role_sql(PASSWORD, 'frunze')
    grants = re.findall(r'GRANT INSERT, UPDATE ON (.+?) TO ' + ROLE, sql)
    assert len(grants) == 1
    assert sorted(t.strip() for t in grants[0].split(',')) == sorted(WRITE_TABLES)
    assert set(WRITE_TABLES) == {'conversations', 'messages', 'audit_log', 'contacts',
                                 'contact_identities', 'assignments', 'calendar_tasks',
                                 'calendar_task_events'}


def test_no_delete_ddl_flags_or_money_rights():
    sql = role_sql(PASSWORD, 'frunze')
    for forbidden in ('DELETE', 'TRUNCATE', 'GRANT ALL', 'SUPERUSER ', 'CREATEDB ', 'CREATEROLE '):
        assert forbidden not in sql.replace('NOSUPERUSER', '').replace('NOCREATEDB', '').replace('NOCREATEROLE', '')
    assert 'REVOKE CREATE ON SCHEMA public' in sql
    assert 'app_flags' not in sql and 'service_payments' not in sql


@pytest.mark.parametrize('password', ['short', 'x' * 31, ('y' * 40) + "'; DROP TABLE x; --"])
def test_weak_or_unsafe_password_refused(password):
    with pytest.raises(ValueError):
        role_sql(password, 'frunze')


@pytest.mark.parametrize('database', ['frunze; DROP', 'Frunze', ''])
def test_unsafe_database_name_refused(database):
    with pytest.raises(ValueError):
        role_sql(PASSWORD, database)
