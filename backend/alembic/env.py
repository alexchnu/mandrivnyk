"""Alembic environment: async engine, metadata taken from the service models."""

import asyncio

from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy.ext.asyncio import create_async_engine

from planner.service import models  # noqa: F401  (registers tables)
from planner.service.config import get_settings
from planner.service.db import Base

target_metadata = Base.metadata
_POSTGIS_TABLES = {"spatial_ref_sys", "geography_columns", "geometry_columns", "topology", "layer"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and (name in _POSTGIS_TABLES or getattr(obj, "schema", None) in ("tiger", "topology")):
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def _url() -> str:
    return context.get_x_argument(as_dictionary=True).get("url") or get_settings().database_url


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
