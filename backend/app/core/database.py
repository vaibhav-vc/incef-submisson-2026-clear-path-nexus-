from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine_options: dict[str, object] = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
    "connect_args": {
        "statement_cache_size": settings.DATABASE_PREPARED_STATEMENT_CACHE_SIZE,
        "prepared_statement_cache_size": settings.DATABASE_PREPARED_STATEMENT_CACHE_SIZE,
    },
}
if settings.DATABASE_POOL_MODE == "null":
    engine_options["poolclass"] = NullPool
else:
    engine_options.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
    )

engine = create_async_engine(settings.DATABASE_URL, **engine_options)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
