from typing import List
from sqlalchemy.orm import attributes
from app.models import OutputDetail # Assuming your OutputDetail model is here

async def update_output_details_hstore_tags(
    output_detail_objs: List[OutputDetail],
    tag_id: int,
    tag_name: str,
) -> None:
    """
    Updates the 'tags' HSTORE column for a list of OutputDetail objects 
    with the given tag ID and name.
    
    Args:
        output_detail_objs: A list of OutputDetail instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key).
        tag_name: The name of the DatabaseReleaseTag (used as the HSTORE value).
    """
    if not output_detail_objs:
        return

    tag_key = str(tag_id)
    tag_value = tag_name

    for od in output_detail_objs:
        # Initialize tags dictionary if None
        if od.tags is None:
            od.tags = {}

        # Add the new tag only if it doesn't already exist in the HSTORE
        if tag_key not in od.tags:
            od.tags[tag_key] = tag_value
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()


async def remove_output_details_hstore_tags(
    output_detail_objs: List[OutputDetail],
    tag_id: int,
) -> None:
    """
    Removes a specific tag ID (key) from the 'tags' HSTORE column for a list 
    of OutputDetail objects.
    
    Args:
        output_detail_objs: A list of OutputDetail instances loaded in the session.
        tag_id: The ID of the DatabaseReleaseTag (used as the HSTORE key to remove).
    """
    if not output_detail_objs:
        return

    tag_key = str(tag_id)

    for od in output_detail_objs:
        # Check if tags is not None and the tag_key exists
        if od.tags is not None and tag_key in od.tags:
            del od.tags[tag_key]
            
            # CRITICAL: Flag the HSTORE column as modified to ensure the DELETE/UPDATE is saved.
            attributes.flag_modified(od, "tags")

    # The caller (API endpoint) is responsible for calling session.commit()