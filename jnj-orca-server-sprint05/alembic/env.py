from alembic import context
from sqlmodel import SQLModel
import sys
import pathlib

# Add project root
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

# Import sync engine, NOT async
from app.core.db import sync_engine
from app.models import user, source, compound, study, database_release, reporting_effort, distribution_list, output_detail   # ensure models are imported so metadata is populated
from sqlmodel.sql.sqltypes import AutoString

target_metadata = SQLModel.metadata

# Tell Alembic to render AutoString as sa.String
def render_item(type_, obj, autogen_context):
    if isinstance(obj, AutoString):
        return "sa.String()"
    return False

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = str(sync_engine.url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    with sync_engine.connect() as connection:  # <-- use sync engine
        context.configure(connection=connection, target_metadata=target_metadata,render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()