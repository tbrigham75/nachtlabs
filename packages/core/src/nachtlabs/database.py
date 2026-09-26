from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nachtlabs.settings import get_settings


@lru_cache
def engine() -> Engine:
    return create_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )


def session() -> Session:
    return Session(engine(), expire_on_commit=False)


@lru_cache
def limiter_engine() -> Engine:
    # Independent transactions must not compete with all checked-out request connections.
    return create_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
