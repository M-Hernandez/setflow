from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import settings

engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def check_db() -> bool:
    """Return True if the database is reachable."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
