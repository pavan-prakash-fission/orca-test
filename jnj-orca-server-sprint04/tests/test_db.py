import pytest
from app.core.db import async_session
from app.models.user import User

@pytest.mark.asyncio
async def test_db_connection():
    async with async_session() as session:
        result = await session.execute("SELECT 1")
        assert result.scalar() == 1
