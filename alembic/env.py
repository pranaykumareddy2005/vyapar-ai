"""Alembic migration environment.

Pulls the database URL from application settings (env-sourced) and targets
``app.db.Base.metadata`` for autogenerate. Domain models are imported here as
modules are added so their tables are visible to autogenerate.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

# Import model modules so Base.metadata is fully populated for autogenerate.
from app.auth import models as _auth_models  # noqa: F401
from app.business import models as _business_models  # noqa: F401
from app.catalog import models as _catalog_models  # noqa: F401
from app.catalogai import models as _catalogai_models  # noqa: F401
from app.config import get_settings
from app.customer import models as _customer_models  # noqa: F401
from app.db import Base
from app.inventory import models as _inventory_models  # noqa: F401
from app.invoice import models as _invoice_models  # noqa: F401
from app.notification import models as _notification_models  # noqa: F401
from app.order import models as _order_models  # noqa: F401
from app.payment import models as _payment_models  # noqa: F401
from app.whatsapp import models as _whatsapp_models  # noqa: F401
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().db_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
