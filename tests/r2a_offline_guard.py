"""Opt-in pytest plugin: deny real HTTP transport for the ENTIRE offline regression run.

Use: pytest -p tests.r2a_offline_guard. MockTransport and in-process ASGI remain usable.
"""

from unittest.mock import patch


def deny(*args, **kwargs):
    raise AssertionError("Real HTTP transport is forbidden during offline verification.")


def pytest_configure(config):
    sync = patch("httpx.HTTPTransport.handle_request", deny)
    async_ = patch("httpx.AsyncHTTPTransport.handle_async_request", deny)
    sync.start()
    async_.start()
    config.add_cleanup(sync.stop)
    config.add_cleanup(async_.stop)
