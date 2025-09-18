# Dependency helpers for FastAPI
from typing import Generator


def get_db() -> Generator:
    # placeholder for SQLAlchemy session
    db = None
    try:
        yield db
    finally:
        pass
