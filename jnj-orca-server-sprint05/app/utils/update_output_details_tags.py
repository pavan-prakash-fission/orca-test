from typing import List
from sqlalchemy.orm import attributes
from app.models import OutputDetail , OutputDetailVersion
from sqlalchemy import select

async def update_output_details_hstore_tags(
    output_detail_versions: List[OutputDetailVersion],
    tag_id: int,
    tag_name: str,
) -> None:
    """
    Updates the 'tags' HSTORE column for a list of OutputDetailVersion objects 
    with the given tag ID and name.
    
    Args:
        output_detail_versions: A list of OutputDetailVersion instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key).
        tag_name: The name of the DatabaseReleaseTag (used as the HSTORE value).
    """
    if not output_detail_versions:
        return

    tag_key = str(tag_id)

    for od in output_detail_versions:

        # Add the new tag only if it doesn't already exist in the HSTORE
        if tag_key not in od.tags:
            od.tags[tag_key] = tag_name
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()


async def remove_output_details_hstore_tags(
    output_detail_versions: List[OutputDetailVersion],
    tag_id: int,
) -> None:
    """
    Removes a specific tag ID (key) from the 'tags' HSTORE column for a list 
    of OutputDetail objects.
    
    Args:
        output_detail_versions: A list of OutputDetailVersion instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key to remove).
    """
    if not output_detail_versions:
        return

    tag_key = str(tag_id)
    for od in output_detail_versions:
        # Check if tags is not None and the tag_key exists
        if od.tags is not None and tag_key in od.tags:
            del od.tags[tag_key]
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the DELETE/UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()


async def update_tag_name_in_output_versions(session, tag_id: int, new_tag_name: str):
    """
    Updates the tag name inside the 'tags' HSTORE column of OutputDetailVersion
    wherever the given tag_id is present.
    """
    tag_key = str(tag_id)

    result = await session.execute(
        select(OutputDetailVersion).where(
            OutputDetailVersion.tags.has_key(tag_key)
        )
    )
    versions = result.scalars().all() 

    for version in versions:
        if version.tags and tag_key in version.tags:
            version.tags[tag_key] = new_tag_name
            attributes.flag_modified(version, "tags")


    await session.commit()