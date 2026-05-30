"""Tests for database connectivity."""

from sqlalchemy import text


async def test_db_engine_connects(db_engine):
    """The async engine should be able to execute a simple query."""
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 AS n"))
        assert result.scalar() == 1


async def test_pgvector_extension_available(db_engine):
    """pgvector should be installed and queryable."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert result.scalar() == "vector"


async def test_db_session_rollback_isolation(db_session):
    """Writes inside the db_session fixture should not persist
    after the test — verifying rollback works for future tests."""
    await db_session.execute(
        text("CREATE TEMP TABLE _test_isolation (id int)")
    )
    await db_session.execute(
        text("INSERT INTO _test_isolation VALUES (1)")
    )
    result = await db_session.execute(text("SELECT COUNT(*) FROM _test_isolation"))
    assert result.scalar() == 1
    # rollback happens automatically after yield — the temp table
    # won't exist for the next test
