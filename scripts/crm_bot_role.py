"""SQL for the least-privilege `frunze_crm` role in the BOT database (B1, предаудит B7).

The CRM in bot-data mode reads the bot's conversations and writes only what its allowed
routes write: messages/audit, takeover/assignment, internal tasks. No DELETE, no DDL, no
money/contract tables, `app_flags` read-only. Tables added by later migrations are NOT
granted automatically — a new grant is a reviewed change.

Usage (on the server, password file 0600 outside git). Pipe straight into psql — never
write the SQL to a file: it contains the plaintext password.
    python3 scripts/crm_bot_role.py --password-file crm-db-password --database frunze       | docker exec -i frunze-travel-db-1 psql -v ON_ERROR_STOP=1 -U postgres -d frunze
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROLE = "frunze_crm"
WRITE_TABLES = (
    # legacy panel tables (app/integrations/crm/db.py)
    "conversations", "messages", "audit_log",
    # takeover / reassign (app/domain/live_assign.py, ContactService)
    "contacts", "contact_identities", "assignments",
    # internal tasks (app/domain/calendar_tasks.py)
    "calendar_tasks", "calendar_task_events",
)


def role_sql(password: str, database: str) -> str:
    if len(password) < 32 or not re.fullmatch(r"[A-Za-z0-9_\-]+", password):
        raise ValueError("password must be >=32 chars of [A-Za-z0-9_-]")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", database):
        raise ValueError("unexpected database name")
    lines = [
        "BEGIN;",
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN "
        f"CREATE ROLE {ROLE} LOGIN; END IF; END $$;",
        f"ALTER ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
        f"NOBYPASSRLS CONNECTION LIMIT 20 PASSWORD '{password}';",
        f"REVOKE ALL ON DATABASE {database} FROM {ROLE};",
        f"GRANT CONNECT ON DATABASE {database} TO {ROLE};",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE};",
        f"REVOKE CREATE ON SCHEMA public FROM {ROLE};",
        f"GRANT USAGE ON SCHEMA public TO {ROLE};",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE};",
        f"GRANT INSERT, UPDATE ON {', '.join(WRITE_TABLES)} TO {ROLE};",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};",
        "COMMIT;",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--database", default="frunze")
    args = parser.parse_args()
    print(role_sql(args.password_file.read_text().strip(), args.database), end="")


if __name__ == "__main__":
    main()
