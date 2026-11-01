from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from retain_ai.config import settings

db_url = settings.get_database_url()

# SQLite needs connect_args check_same_thread=False
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine = create_async_engine(
    db_url,
    echo=False,
    future=True,
    connect_args=connect_args
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

