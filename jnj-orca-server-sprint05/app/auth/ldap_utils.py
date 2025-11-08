import logging
import os
from typing import Optional, List
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.utils.conv import escape_filter_chars
from fastapi import HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone


# Environment Variables
LDAP_SERVER_AVAILABLE = os.getenv("LDAP_SERVER_AVAILABLE", "False").lower() == "true"
LDAP_SERVER_URI = os.getenv("LDAP_SERVER_URI", "")
LDAP_BIND_DN = os.getenv("LDAP_BIND_DN", "")
LDAP_BIND_PASSWORD = os.getenv("LDAP_BIND_PASSWORD", "")
SEARCH_BASE = os.getenv("ORG_UNIT", "")
LDAP_ALLOWED_GROUPS = os.getenv("LDAP_ALLOWED_GROUPS", "")
LDAP_GROUP_ATTRIBUTE = os.getenv("LDAP_GROUP_ATTRIBUTE", "member")
LDAP_SEARCH_ATTRIBUTE = os.getenv("LDAP_SEARCH_ATTRIBUTE", "sAMAccountName")

logger = logging.getLogger(__name__)

class LDAPUserSearch(BaseModel):
    """
    Model for LDAP user search results.
    Matches UserRead schema for consistent API responses.
    """
    id: int  # Temporary ID for display purposes (not a real DB ID)
    username: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_staff: bool = False
    is_active: bool = True
    is_superuser: bool = False
    role: str = "reviewer"
    date_joined: datetime
    last_login: Optional[datetime] = None
    fullName: Optional[str] = None
    dn: Optional[str] = None  # LDAP Distinguished Name


def ldap_connect() -> Connection:
    """
    Establish connection to LDAP server using service account.
    
    Returns:
        Connection: Active LDAP connection
        
    Raises:
        HTTPException: If LDAP is not configured or connection fails
    """
    if not LDAP_SERVER_URI:
        raise HTTPException(
            status_code=500, 
            detail="LDAP not configured (LDAP_SERVER_URI missing)"
        )
    
    server = Server(LDAP_SERVER_URI, get_info=ALL)
    
    if not LDAP_BIND_DN or not LDAP_BIND_PASSWORD:
        raise HTTPException(
            status_code=500, 
            detail="LDAP bind credentials not configured"
        )
    
    try:
        conn = Connection(
            server, 
            user=LDAP_BIND_DN, 
            password=LDAP_BIND_PASSWORD, 
            auto_bind=True
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LDAP bind failed: {e}")


def search_ldap_users(query: str, limit: int = 25, offset: int = 0) -> List[LDAPUserSearch]:
    """
    Search for users in LDAP directory.
    
    Args:
        query: Search term (username, email, or name)
        limit: Maximum number of results to return
        offset: Number of results to skip (for pagination)
        
    Returns:
        List[LDAPUserSearch]: List of LDAP users matching the search
        
    Raises:
        HTTPException: If LDAP search fails
        
    Note:
        - LDAP doesn't support native offset pagination, so we fetch all results
          and slice them in memory. For large result sets, consider other approaches.
        - Uses 'jnjmsusername' and 'sAMAccountName' for username lookup
        - Input is sanitized to prevent LDAP injection attacks
        
    """
    
    if not SEARCH_BASE:
        raise HTTPException(
            status_code=400, 
            detail="LDAP search base (ORG_UNIT) is empty or invalid"
        )
    
    # Sanitize input to prevent LDAP injection attacks
    sanitized_query = escape_filter_chars(query)
    
    # Build LDAP filter for flexible search
    # Searches in: username (jnjmsusername or sAMAccountName), common name, and email
    attr = LDAP_SEARCH_ATTRIBUTE
    ldap_filter = f"(|({attr}=*{sanitized_query}*)(jnjmsusername=*{sanitized_query}*)(cn=*{sanitized_query}*)(mail=*{sanitized_query}*))"
    
    try:
        with ldap_connect() as conn:
            conn.search(
                SEARCH_BASE,
                ldap_filter,
                SUBTREE,
                attributes=['jnjmsusername', 'sAMAccountName', 'cn', 'mail', 
                           'distinguishedName', 'givenName', 'sn'],
                size_limit=limit + offset  # Fetch enough for pagination
            )
            
            results: List[LDAPUserSearch] = []
            
            for idx, entry in enumerate(conn.entries, start=1):
                e = entry.entry_attributes_as_dict
                
                # Extract Distinguished Name
                dn_list = e.get('distinguishedName')
                if isinstance(dn_list, list) and dn_list:
                    dn = dn_list[0]
                else:
                    dn = e.get('distinguishedName') or entry.entry_dn or ""
                
                if not dn:
                    continue
                
                # Extract username (try jnjmsusername first, fallback to sAMAccountName)
                username = None
                if 'jnjmsusername' in e:
                    username = e.get('jnjmsusername', [None])[0] if isinstance(e.get('jnjmsusername'), list) else e.get('jnjmsusername')
                if not username and 'sAMAccountName' in e:
                    username = e.get('sAMAccountName', [None])[0] if isinstance(e.get('sAMAccountName'), list) else e.get('sAMAccountName')
                
                if not username:
                    continue
                
                # Extract other attributes
                email = e.get('mail', [None])[0] if isinstance(e.get('mail'), list) else e.get('mail')
                first_name = e.get('givenName', [None])[0] if isinstance(e.get('givenName'), list) else e.get('givenName')
                last_name = e.get('sn', [None])[0] if isinstance(e.get('sn'), list) else e.get('sn')
                
                # Create full name
                full_name = f"{first_name or ''} {last_name or ''}".strip()
                
                results.append(LDAPUserSearch(
                    id=idx,  # Temporary ID for display (not a real DB ID)
                    dn=dn,
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    fullName=full_name if full_name else None,
                    is_staff=False,
                    is_active=True,
                    is_superuser=False,
                    role="reviewer",
                    date_joined=datetime.now(timezone.utc),
                    last_login=None
                ))
            
            # Apply offset pagination (slice results in memory)
            paginated_results = results[offset:offset + limit]
            return paginated_results
            
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"LDAP search failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=400, detail="LDAP search failed")
        