"""Compatibility import; the demo provider lives in the application package."""

from app.agent.demo_provider import DemoProvider

__all__ = ["DemoProvider"]
