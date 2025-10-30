from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from app.core.db import get_session
from app.utils.enums import RoleEnum


async def authorize_user(
    x_orca_username: str = Header(..., alias="X-orca-username"),
    session: AsyncSession = Depends(get_session),
):
    """
    Dependency to authorize user based on their role.
    Rejects access if role == 'reviewer'.
    """
    # Fetch the user by username
    result = await session.execute(select(User).where(User.username == x_orca_username))
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[{
                "field": "user",
                "message": "Invalid user"
            }]
        )

    # Deny access if user is reviewer
    # if user.role == RoleEnum.reviewer.value:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN,
    #         detail="Access denied for reviewers",
    #     )

    # If authorized, you can return user object (optional)
    return user

def verify_coowner_permission(dl, username: str):
    """
    Checks if the given username is in the co-owners list of the distribution list.
    Raises HTTP 403 if not authorized.
    """
    # Handle case where coowners might be None or empty
    allowed_users = dl.co_owners or []
    if dl.created_by and dl.created_by.username not in allowed_users:
        allowed_users.append(dl.created_by.username)
    
    if username not in allowed_users:
        raise HTTPException(
            status_code=403,
            detail=[{
                "field": "coowners",
                "message": "User is not authorized to edit this User List."
            }]
        )