from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.models import OutputDetail
from app.utils.enums import DocsSharedAs
from sqlmodel import select
from sqlalchemy.orm import selectinload
from app.utils.audit_log import create_audit_log

async def update_output_draft_status(
    session: AsyncSession,
    output_detail_objs: List[OutputDetail],
    identify_as_draft: bool = True,
    toggle_mode: bool = False
):

    for od in output_detail_objs:
        old_value = od.docs_shared_as

        if toggle_mode:
            # Toggling logic
            if old_value is None or old_value == DocsSharedAs.PROD.value:
                new_env_value = DocsSharedAs.PREPROD.value
            else:
                new_env_value = DocsSharedAs.PROD.value
        else:
            # Normal mode (based on input flag)
            new_env_value = DocsSharedAs.PREPROD.value if identify_as_draft else DocsSharedAs.PROD.value

        od.docs_shared_as = new_env_value
        session.add(od)

        # Audit log
        if old_value != new_env_value:
            await create_audit_log(
                session=session,
                user_name="system",
                action="UPDATE",
                object_type="output_details",
                object_key=str(od.id),
                object_property="docs_shared_as",
                old_value=old_value,
                new_value=new_env_value
            )


async def clear_draft_status_from_orphan(
    session: AsyncSession,
    output_detail_ids: list[int]
):
    # 1️⃣ Fetch all OutputDetail objects in one go
    result = await session.execute(
        select(OutputDetail)
        .options(selectinload(OutputDetail.database_release_tags))
        .where(OutputDetail.id.in_(output_detail_ids))
    )

    # 2️⃣ Loop through result objects instead of querying inside loop
    output_details = result.scalars().all()

    for od in output_details:
        if len(od.database_release_tags) == 0:
            old_value = od.docs_shared_as
            od.docs_shared_as = None
            session.add(od)

            # Audit log
            if old_value != od.docs_shared_as:
                await create_audit_log(
                    session=session,
                    user_name="system",
                    action="UPDATE",
                    object_type="output_details",
                    object_key=str(od.id),
                    object_property="docs_shared_as",
                    old_value=old_value,
                    new_value=od.docs_shared_as
                )

    # 3️⃣ Single commit
    await session.commit()
   