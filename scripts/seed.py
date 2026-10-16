"""Non-destructive synthetic catalog upsert, only to dedicated local demo/test DBs."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.safety import require_demo_database
from app.db.seed import seed_catalog
from app.db.session import build_engine


def main() -> None:
    settings = Settings()
    require_demo_database(settings.database_url.get_secret_value())
    engine = build_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            seed_catalog(db)
        print("Synthetic catalog seeded: 1 clinic, 2 practitioners, 2 types, 10 weekly schedules.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
