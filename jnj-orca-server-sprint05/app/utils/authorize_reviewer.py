from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from sqlalchemy.future import select

from app.utils.get_user_output_mapping import get_accessible_output_ids_for_reviewer
from app.models.output_detail import OutputDetail

async def authorize_reviewer(current_user, file_ids, session: AsyncSession):
    """
    Authorize if the reviewer has access to the requested files.
    """
    accessible_output_ids = await get_accessible_output_ids_for_reviewer(
    session, current_user.username, list(file_ids)
    )
    denied_output_ids = set(file_ids) - set(accessible_output_ids)
    if denied_output_ids:
    # Single-file request → explicit message naming the file
        if len(file_ids) == 1:
            denied_id = list(denied_output_ids)[0]
            query = select(OutputDetail.identifier).where(OutputDetail.id == denied_id)
            result = await session.execute(query)
            identifier = result.scalar_one_or_none()
            raise HTTPException(status_code=403, detail=f"You do not have access to this file: {identifier}")
        # Bulk request → generic message
        raise HTTPException(status_code=403, detail="You do not have access to one or more files.")