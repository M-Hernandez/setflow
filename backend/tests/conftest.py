import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.main import app


# --- HTTP client ---


@pytest.fixture
async def client():
    """Async HTTP client wired to the FastAPI app. No real server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Database ---


@pytest.fixture
async def db_engine():
    """Async engine for tests. Each test gets a fresh engine to avoid
    connection state leaking between tests."""
    engine = create_async_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Per-test database session that rolls back after each test.
    Use this for any test that writes to the database — it keeps
    tests isolated without needing to truncate tables."""
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()
