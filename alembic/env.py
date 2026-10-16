from alembic import context
from app.core.config import Settings
from app.db.models import Base
from app.db.safety import require_demo_database
from app.db.session import build_engine

target_metadata = Base.metadata


def run_migrations_offline():
    settings = Settings()
    context.configure(
        url=settings.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    provided = context.config.attributes.get("connection")
    if provided is not None:
        require_demo_database(provided.engine.url.render_as_string(hide_password=False))
        context.configure(connection=provided, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    settings = Settings()
    require_demo_database(settings.database_url.get_secret_value())
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
