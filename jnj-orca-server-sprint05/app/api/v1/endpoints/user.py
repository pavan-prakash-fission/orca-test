from typing import Union, List
from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination.cursor import CursorParams, CursorPage
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional
from app.core.db import get_session
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate, LoginResponse, LoginRequest
from datetime import datetime, timezone
from app.auth.ldap_utils import (
    LDAP_SERVER_AVAILABLE, 
    search_ldap_users,
    LDAPUserSearch
)


router = APIRouter()


# Login User (dummy - no authentication)
@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_session)):
    """
    Dummy login endpoint - authenticates user by username only.
    Returns username and role if user exists.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return LoginResponse(username=user.username, role=user.role, user_id=user.id)


# Create User
@router.post("/", response_model=UserRead)
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_session)):
    new_user = User(**user_in.model_dump())   # ✅ reuse schema
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


# Get single user
@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Get all users
@router.get("/", response_model=Union[CursorPage[UserRead], List[LDAPUserSearch]])
async def list_users(
    params: CursorParams = Depends(), 
    search: Optional[str] = None, 
    limit: int = 25,
    offset: int = 0,
    db: AsyncSession = Depends(get_session)
):
    """
    Retrieve paginated User records with optional search filter.
    
    - If LDAP_SERVER_AVAILABLE=True: Searches LDAP directory (uses limit/offset pagination)
    - If LDAP_SERVER_AVAILABLE=False: Searches local database (uses cursor pagination)
    
    Args:
        params: Cursor pagination parameters (for DB search)
        search: Optional search term for filtering users
        limit: Maximum results per page (for LDAP search)
        offset: Number of results to skip (for LDAP search)
        db: Database session
        
    Returns:
        - CursorPage[UserRead] when searching database
        - List[LDAPUserSearch] when searching LDAP
    """
    
    if LDAP_SERVER_AVAILABLE:
        print("LDAP search mode activated = ", LDAP_SERVER_AVAILABLE)
        # ========== LDAP Search ==========
        if not search:
            # LDAP search requires a query term
            raise HTTPException(
                status_code=400, 
                detail="Search parameter required when using LDAP"
            )
        
        try:
            ldap_users = search_ldap_users(query=search, limit=limit, offset=offset)
            return ldap_users
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LDAP search error: {e}")
    
    else:
        print("Database search mode activated")
        # ========== Database Search (existing logic) ==========
        query = select(User)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                (User.username.ilike(search_term)) |
                (User.first_name.ilike(search_term)) |
                (User.last_name.ilike(search_term)) |
                (User.email.ilike(search_term))
            )
        
        # Order by ID for cursor pagination
        query = query.order_by(User.id)
        
        return await paginate(db, query, params)


# Update User
@router.put("/{user_id}", response_model=UserRead)
async def update_user(user_id: int, user_in: UserUpdate, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user_in.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        setattr(user, key, value)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# Delete User
@router.delete("/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    return {"ok": True}