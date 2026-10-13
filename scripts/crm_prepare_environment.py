"""Generate fresh service-only secrets locally on the Linux CRM host; never print them."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets


def prepare(directory: Path, origin: str, release: str):
    if os.name != 'posix' or not re.fullmatch(r'https://[a-z0-9][a-z0-9.-]+',origin):
        raise RuntimeError('Run on the Linux host with an explicit HTTPS origin')
    if not re.fullmatch('[a-f0-9]{20,64}',release):
        raise RuntimeError('Manifest release identity required')
    directory=directory.resolve()
    names=('crm.env','compose.env','first-login.json','database-role.sql')
    if any((directory/name).exists() for name in names):
        raise RuntimeError('Refuse to replace existing service credentials')
    os.umask(0o077)
    directory.mkdir(parents=True,exist_ok=True)
    db_password=secrets.token_hex(32)
    owner_password=secrets.token_hex(32)
    login_password=secrets.token_urlsafe(30)
    values={
        'DATABASE_URL':'postgresql+asyncpg://frunze_crm:'+db_password+'@db:5432/frunze_crm',
        'CRM_STANDALONE_ENABLED':'true','CRM_PUBLIC_ORIGIN':origin,
        'CRM_DATABASE_NAME':'frunze_crm','CRM_RELEASE_REVISION':release,
        'SESSION_SECRET':secrets.token_hex(48),'SESSION_HTTPS_ONLY':'true',
        'ADMIN_ENABLED':'true','DEMO_LOGIN':'false','PANEL_BACKEND':'postgres',
        'CRM_BACKEND':'postgres','STATE_BACKEND':'memory','AUTHZ_ENFORCE_ENABLED':'true',
        'MANAGERS':json.dumps([{'login':'alan','name':'Alan','password':login_password,'admin':True}],separators=(',',':')),
        'BOTS':'[]','TELEGRAM_BOTS':'[]','ADMIN_BASE_URL':origin,
        'ADMIN_NEW_LOOK_ENABLED':'true','ADMIN_CHAT_REDESIGN_ENABLED':'true',
        'ADMIN_WORKDAY_ENABLED':'true','SERVICE_CASES_ENABLED':'true','ADMIN_KG_ENTRY_ENABLED':'true',
        'KG_KNOWLEDGE_POLICY_REF':'','KG_KNOWLEDGE_POLICY_SHA256':'',
        'OPENROUTER_API_KEY':'','ANTHROPIC_API_KEY':'','STT_API_KEY':'',
        'WAPPI_TOKEN':'','TELEGRAM_BOT_TOKEN':'','BITRIX24_WEBHOOK_URL':'',
        'MANAGERS_TELEGRAM_BOT_TOKEN':'','MANAGERS_TELEGRAM_CHAT_ID':'',
    }
    (directory/'crm.env').write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
    (directory/'compose.env').write_text('CRM_RELEASE='+release+'\nCRM_PUBLIC_ORIGIN='+origin+
        '\nCRM_PG_OWNER_PASSWORD='+owner_password+'\n')
    (directory/'first-login.json').write_text(json.dumps({'origin':origin,'login':'alan','password':login_password}))
    # Hex-only generated password is safe SQL text; this file stays mode0600 on host.
    (directory/'database-role.sql').write_text("CREATE ROLE frunze_crm LOGIN PASSWORD '"+db_password+
        "' NOSUPERUSER NOCREATEDB NOCREATEROLE;\nALTER DATABASE frunze_crm OWNER TO frunze_crm;\n")
    print('Created new private service credentials; no existing bot configuration used')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--release',required=True)
    args=parser.parse_args()
    prepare(args.directory,args.origin,args.release)
