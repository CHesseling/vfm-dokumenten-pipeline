from sqlmodel import create_engine, Session

_engine = None


def get_engine(database_url: str):
    global _engine
    if _engine is None:
        _engine = create_engine(database_url)
    return _engine


def get_session():
    from app.config import get_settings

    engine = get_engine(get_settings().database_url)
    with Session(engine) as session:
        yield session
