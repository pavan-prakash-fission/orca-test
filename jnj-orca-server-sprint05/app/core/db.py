from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.config.settings import settings
from sqlmodel import create_engine
from sqlmodel import Session

DATABASE_URL = settings.db_url
SYNC_DATABASE_URL = DATABASE_URL.replace("asyncpg", "psycopg2")

engine = create_async_engine(DATABASE_URL, echo=settings.debug)
sync_engine = create_engine(SYNC_DATABASE_URL, echo=True, future=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

# ✅ Dependency for FastAPI
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session