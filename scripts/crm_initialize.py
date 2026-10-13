"""Initialize only a fresh dedicated CRM database; no demo people or approvals."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def empty_database(url):
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
            if tables:
                raise RuntimeError('Fresh initialization refused: database already has tables')
    finally:
        await engine.dispose()


async def check_resume(url):
    from sqlalchemy import select,func,text
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from app.crm_main import SCHEMA
    from app.crm_intake import CrmBootstrap
    from app.integrations.crm.db import Conversation
    from app.domain.models import ServiceCase
    engine=create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            marker=await session.get(CrmBootstrap,'standalone-v1')
            if marker is None or marker.state != 'pending':
                raise RuntimeError('Only a recorded incomplete bootstrap can be resumed')
            if await session.scalar(text('SELECT version_num FROM alembic_version')) != SCHEMA:
                raise RuntimeError('Incomplete migration requires separate recovery')
            for model in (Conversation,ServiceCase):
                if await session.scalar(select(func.count()).select_from(model)):
                    raise RuntimeError('Refuse bootstrap resume on an in-use database')
    finally:
        await engine.dispose()


async def bootstrap(url, source, administrator):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from app.integrations.crm.db import Base
    from app.crm_intake import CrmIntakeReceipt,CrmBootstrap
    from app.domain.models import Product,WorkflowVersion
    from app.domain.permissions import Actor
    from app.domain.service_cases import create_product,publish_version
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    actor = Actor(administrator,is_full_admin=True)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sm = async_sessionmaker(engine,expire_on_commit=False)
        async with sm() as session, session.begin():
            marker = await session.get(CrmBootstrap,'standalone-v1')
            if marker is None:
                marker = CrmBootstrap(key='standalone-v1',state='pending',
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                session.add(marker)
            elif marker.source_sha256 != hashlib.sha256(source.read_bytes()).hexdigest():
                raise RuntimeError('Bootstrap source changed')
            elif marker.state == 'ready':
                return
            product = await session.scalar(select(Product).where(Product.code=='kg_entry_intake'))
            if product is None:
                product = await create_product(session,code='kg_entry_intake',
                    name='Въезд в Кыргызстан — обращение',direction='visa',by=actor)
            elif product.direction != 'visa' or not product.active:
                raise RuntimeError('Unexpected intake product state')
            # One inert container stage. Actual SOP transitions still require their
            # separately approved process policy; no SLA, first task or price seed.
            version = await session.scalar(select(WorkflowVersion).where(WorkflowVersion.product_id==product.id))
            if version is None:
                await publish_version(session,product.id,
                    [{'code':'KG-INTAKE','name':'Обращение'}],{'KG-INTAKE':[]},administrator,by=actor)
            elif (version.stages != [{'code':'KG-INTAKE','name':'Обращение'}] or
                  version.transitions != {'KG-INTAKE':[]} or not version.published_at or
                  product.current_version_id != version.id):
                raise RuntimeError('Unexpected intake workflow state')
        set_id = await create_kg_entry_set(engine,actor=actor)
        result = await import_bundle(engine,actor=actor,set_id=set_id,
            directory=ROOT/'knowledge/kg_entry/draft-v1.1',source=source,
            catalog=ROOT/'knowledge/kg_entry/conditions_v1_1/catalog.json')
        if not result.accepted:
            raise RuntimeError('Draft source import did not pass validation')
        async with sm() as session, session.begin():
            marker = await session.get(CrmBootstrap,'standalone-v1',with_for_update=True)
            marker.state = 'ready'
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--fresh-database',action='store_true')
    mode.add_argument('--resume-bootstrap',action='store_true')
    parser.add_argument('--source',type=Path,required=True)
    args = parser.parse_args()
    from app.crm_main import validate_configuration
    from app.config import settings
    validate_configuration()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2':
        raise RuntimeError('Original source PDF hash mismatch')
    if args.fresh_database:
        asyncio.run(empty_database(settings.database_url))
    else:
        asyncio.run(check_resume(settings.database_url))
    from alembic.config import Config
    from alembic import command
    config = Config(str(ROOT/'alembic.ini'))
    config.set_main_option('script_location',str(ROOT/'alembic'))
    config.set_main_option('sqlalchemy.url',settings.database_url.replace('%','%%'))
    # env.py gives ALEMBIC_DATABASE_URL priority; prevent an ambient target override.
    import os
    if os.environ.get('ALEMBIC_DATABASE_URL') not in (None,'',settings.database_url):
        raise RuntimeError('Conflicting migration target')
    command.upgrade(config,'head')
    administrator = next(m.login for m in settings.managers if m.admin)
    asyncio.run(bootstrap(settings.database_url,args.source,administrator))
    print('Dedicated CRM initialized: empty intake, no clients, draft sources, no source approvals')


if __name__ == '__main__':
    main()
