from datetime import UTC, datetime


def now() -> datetime:
    """Return the current time in UTC. Can be overridden in FastAPI dependencies for testing."""
    return datetime.now(UTC)
