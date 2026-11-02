from collections.abc import Iterable

from sqlalchemy.engine import URL, make_url

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
# TLS settings for a managed database (e.g. sslmode=verify-full with a CA bundle). Any
# other key, notably libpq's host/hostaddr/options, could redirect or alter the target.
ALLOWED_QUERY_KEYS = frozenset({"sslmode", "sslrootcert"})


def require_demo_database(
    raw_url: str, *, test_only: bool = False, allowed_hosts: Iterable[str] = ()
) -> URL:
    """Reject non-demo targets before any connection or mutation.

    The test-only check is loopback-only with no query string, whatever
    ``allowed_hosts`` says: suites and demos rebuild or clean the schema. Migrations and
    seeding also accept the exact hostnames an operator lists in DATABASE_ALLOWED_HOSTS.
    """
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError("Select the dedicated local synthetic PostgreSQL database.") from None
    if test_only:
        names, hosts, query_keys = {"clinic_scheduling_test"}, LOOPBACK_HOSTS, frozenset()
    else:
        names = {"clinic_scheduling_dev", "clinic_scheduling_test"}
        hosts = LOOPBACK_HOSTS | set(allowed_hosts)
        query_keys = ALLOWED_QUERY_KEYS
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in hosts
        or url.database not in names
        or url.username != "clinic_demo"
        or not set(url.query) <= query_keys
    ):
        raise ValueError("Select the dedicated local synthetic PostgreSQL database.")
    return url
