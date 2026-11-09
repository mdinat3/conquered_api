from logging.config import fileConfig
from pathlib import Path
import sys
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import ensure_database
from app.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import after the app package has loaded env variables from dev.env.
from app.config import settings  # noqa: E402  # pylint: disable=wrong-import-position

config.set_main_option(
    "sqlalchemy.url",
    "mysql+pymysql://"
    f"{quote_plus(settings.mysql_username)}:{quote_plus(settings.mysql_pass)}"
    f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_db}",
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    ensure_database()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
