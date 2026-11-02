"""Create or update the runtime database role; run after every migration.

Connects as the migration owner (``clinic_demo``) through the same guard as migrations
and seeding. The runtime role ``clinic_app`` can log in and read and write rows in the
application tables, nothing else: no DDL, no table ownership, and only read access to
``alembic_version``. Re-running it resets the password and re-applies the grants, so it
also covers tables added by later migrations.
"""

from psycopg import sql
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import Settings
from app.db.safety import require_demo_database
from app.db.session import build_engine

APP_ROLE = "clinic_app"


class RoleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    clinic_app_password: SecretStr


def statements(database: str, password: str) -> list[sql.Composable]:
    role = sql.Identifier(APP_ROLE)
    return [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            role
        ),
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role),
        sql.SQL("REVOKE INSERT, UPDATE, DELETE ON public.alembic_version FROM {}").format(role),
        sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)),
    ]


def main() -> None:
    settings = Settings()
    url = require_demo_database(
        settings.database_url.get_secret_value(), allowed_hosts=settings.allowed_database_hosts
    )
    password = RoleSettings().clinic_app_password.get_secret_value()
    if len(password) < 16:
        raise ValueError("CLINIC_APP_PASSWORD must be at least 16 characters.")
    engine = build_engine(settings)
    try:
        with engine.begin() as connection, connection.connection.cursor() as cursor:
            # psycopg composes identifiers and the password literal itself; DDL takes
            # no bind parameters.
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
            exists = cursor.fetchone() is not None
            if not exists:
                cursor.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(APP_ROLE)))
            for statement in statements(url.database, password):
                cursor.execute(statement)
        print(f"Role {APP_ROLE}: {'updated' if exists else 'created'}; DML grants applied.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
