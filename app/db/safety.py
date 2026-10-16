from sqlalchemy.engine import URL, make_url


def require_demo_database(raw_url: str, *, test_only: bool = False) -> URL:
    """Reject non-local/non-demo targets before any connection or mutation."""
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("Select the dedicated local synthetic PostgreSQL database.") from None
    names = (
        {"clinic_scheduling_test"}
        if test_only
        else {"clinic_scheduling_dev", "clinic_scheduling_test"}
    )
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database not in names
        or url.username != "clinic_demo"
        or url.query
    ):
        raise ValueError("Select the dedicated local synthetic PostgreSQL database.")
    return url
