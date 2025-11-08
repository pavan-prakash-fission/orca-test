"""
OutputDetail filters for API v1.
"""
from typing import Optional, List, Any

from fastapi import Query, HTTPException
from pydantic import field_validator
from fastapi_filter.contrib.sqlalchemy import Filter
from sqlalchemy.sql import Select, func
from sqlalchemy import and_, select, literal, any_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.expression import false

from app.utils.search_type_filter import BooleanSearchFilter
from app.config.settings import settings
from app.models import (
    OutputDetail,
    Source,
    OutputDetailVersion
)


class OutputDetailFilter(Filter):
    """
    Filter definition for OutputDetail model.
    """
    title: Optional[str] = Query(
        None,
        description="Boolean | Plain title for filtering."
    )
    tag_name: Optional[str] = Query(
        None,
        description="Tag name for filtering."
    )
    tag_id__in: Optional[List[int]] = Query(
        None,
        description="Tag IDs for filtering."
    )
    source_name: Optional[str] = Query(
        None,
        description="Source name for filtering."
    )
    source_id: Optional[int] = Query(
        None,
        description="Source ID for filtering."
    )
    compound_name: Optional[str] = Query(
        None,
        description="Compound name for filtering."
    )
    compound_id__in: Optional[List[int]] = Query(
        None,
        description="Compound IDs for filtering."
    )
    study_name: Optional[str] = Query(
        None,
        description="Study name for filtering."
    )
    study_id__in: Optional[List[int]] = Query(
        None,
        description="Study IDs for filtering."
    )
    database_release_name: Optional[str] = Query(
        None,
        description="Database release name."
    )
    database_release_id__in: Optional[List[int]] = Query(
        None,
        description="Database Release IDs."
    )
    reporting_effort_name: Optional[str] = Query(
        None,
        description="Reporting effort name."
    )
    reporting_effort_id__in: Optional[List[int]] = Query(
        None,
        description="Reporting Effort IDs.")
    file_type: Optional[str] = Query(
        None,
        description="File type (e.g., pdf, docx)."
    )
    file_exists: Optional[bool] = Query(
        None,
        description="Filter by file availability."
    )
    converted_file_exists: Optional[bool] = Query(
        None,
        description="Filter by converted file availability."
    )
    identifier: Optional[str] = Query(
        None,
        description="Identifier for filtering."
    )
    user: str = Query(
        "reviewer",
        description="Username for access control filtering."
    )
    advanced_search: Optional[bool] = Query(
        True,
        description="Enable advanced search features."
    )
    outdated_outputs: Optional[bool] = Query(
        None,
        description="Filter for outputs that are out of sync."
    )
    docs_shared_as: Optional[str] = Query(
        None,
        description="Docs Shared As filtering."
    )
    scan_recursively: Optional[bool] = Query(
        True,
        description="Recursively scan hierarchy levels."
    )
    version_name: Optional[str] = Query(
        None,
        description="Output detail version for filtering."
    )

    class Config:
        """
            Pydantic configuration.
            Ignore extra fields to allow flexible query parameters.
        """
        extra = "ignore"

    @field_validator(
            "*",
            mode="before"
            )
    @classmethod
    def strip_whitespace_named(cls, value: Optional[str]) -> Optional[str]:
        """
        Trim whitespace for string fields.
        """
        return value.strip() if isinstance(value, str) else value

    @field_validator(
            "tag_id__in",
            "compound_id__in",
            "study_id__in",
            "database_release_id__in",
            "reporting_effort_id__in",
            mode="before",
            )
    @classmethod
    def split_ids(cls, value: Optional[str]) -> Optional[List[int]]:
        """
        Convert comma-separated IDs into a list of integers.
        """
        if isinstance(value, str):
            return [int(x) for x in value.split(",") if x.strip().isdigit()]
        return value


def _apply_level_filter(
    stmt: Select[Any],
    level: str,
) -> Select[Any]:
    """
    Apply hierarchy-level filtering.
    only return data exactly at the specified level.
    """

    # Conditions for each exact level (non-recursive)
    level_conditions_exact = {
        'compound': and_(
            OutputDetail.compound_id.isnot(None),
            OutputDetail.study_id.is_(None),
            OutputDetail.database_release_id.is_(None),
            OutputDetail.reporting_effort_id.is_(None),
        ),
        'study': and_(
            OutputDetail.compound_id.isnot(None),
            OutputDetail.study_id.isnot(None),
            OutputDetail.database_release_id.is_(None),
            OutputDetail.reporting_effort_id.is_(None),
        ),
        'database_release': and_(
            OutputDetail.compound_id.isnot(None),
            OutputDetail.study_id.isnot(None),
            OutputDetail.database_release_id.isnot(None),
            OutputDetail.reporting_effort_id.is_(None),
        )
    }

    stmt = stmt.where(level_conditions_exact[level])

    return stmt


def _apply_boolean_filter(
        stmt: Select[Any],
        value: str,
        column: InstrumentedAttribute[Any],
        label: str
        ) -> Select[Any]:

    """
    Helper to apply BooleanSearchFilter with error handling.
    """
    try:
        condition = BooleanSearchFilter.build_query(value, column)
        return stmt.where(condition)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} filter: {exc}"
            ) from exc
    
def _apply_array_boolean_filter(
    stmt: Select[Any],
    value: str,
    array_column: InstrumentedAttribute[Any],
    label: str
) -> Select[Any]:
    """
    Helper to apply BooleanSearchFilter for array columns with error handling.
    """
    try:
        condition = BooleanSearchFilter.build_array_filter(value, array_column)
        return stmt.where(condition)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} filter: {exc}"
        ) from exc


async def apply_filter(
        session: AsyncSession,
        stmt: Select[Any],
        filters: OutputDetailFilter,
        ) -> Select[Any]:
    """
    Apply filters to a SQLAlchemy statement for OutputDetail.
    Refactored to reduce redundancy and improve maintainability.
    """

    # --- BooleanSearchFilter-based fields ---
    boolean_filters = {
        filters.title: (
            OutputDetail.title,
            "title"
            ),
        filters.source_name: (
            OutputDetail.source_name,
            "source_name"
            ),
        filters.compound_name: (
            OutputDetail.compound_name,
            "compound_name"
            ),
        filters.study_name: (
            OutputDetail.study_name,
            "study_name"
            ),
        filters.database_release_name: (
            OutputDetail.database_release_name,
            "database_release_name"
            ),
        filters.reporting_effort_name: (
            OutputDetail.reporting_effort_name,
            "reporting_effort_name"
            ),
        filters.identifier: (
            OutputDetail.identifier,
            "identifier"),
    }

    for value, (column, label) in boolean_filters.items():
        if value:
            if filters.advanced_search:
                stmt = _apply_boolean_filter(stmt, value, column, label)
            else:
                # stmt = stmt.where(column.ilike(f"%{value}%"))
                stmt = stmt.where(column.ilike(value))
    # --- Simple ILIKE filters ---
    file_type_groups = {
        "doc": ["doc", "docx"],
        "xls": ["xls", "xlsx"],
        "ppt": ["ppt", "pptx"],
        "xml": ["xml", "xsl"],
        "html": ["htm", "html"],
        # Types that don't have a group are mapped to themselves in a list
        "rtf": ["rtf"],
        "pdf": ["pdf"],
        "png": ["png"],
        "svg": ["svg"],
        "csv": ["csv"],
        "zip": ["zip"],
    }
    allowed_file_types = set(file_type_groups.keys())

    if filters.file_type:
        file_type = filters.file_type.lower()
        if file_type not in allowed_file_types:
            # Return no data if file_type is not allowed
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file_type : {file_type}."
                )
        # Apply the filter if valid
        search_types = file_type_groups[file_type]
        stmt = stmt.where(
            func.lower(OutputDetail.file_type).in_(search_types)
        )

    # --- IN filters ---
    in_filters = [
        (filters.compound_id__in, OutputDetail.compound_id),
        (filters.study_id__in, OutputDetail.study_id),
        (filters.database_release_id__in, OutputDetail.database_release_id),
        (filters.reporting_effort_id__in, OutputDetail.reporting_effort_id),
    ]


    # If not scanning recursively, determine the most specific level
    filter_level = None
    if not filters.scan_recursively:

        if (filters.source_id and
            filters.compound_id__in is None and
            filters.study_id__in is None and
            filters.database_release_id__in is None and
            filters.reporting_effort_id__in is None):

            return None
        if filters.database_release_id__in:
            filter_level = 'database_release'
        elif filters.study_id__in:
            filter_level = 'study'
        elif filters.compound_id__in:
            filter_level = 'compound'

    if filter_level is not None:

        stmt = _apply_level_filter(
            stmt=stmt,
            level=filter_level,
        )

    for values, column in in_filters:
        if values:
            stmt = stmt.where(column.in_(values))

    # --- Exact match filters ---
    if filters.source_id:
        stmt = stmt.where(OutputDetail.source_id == filters.source_id)

    # --- Version filters ---
    if filters.version_name:
        version_expr = func.concat(
            OutputDetailVersion.version_major, '.',
            OutputDetailVersion.version_minor, '.',
            OutputDetailVersion.version_patch
        )

        if filters.advanced_search:
            stmt = stmt.where(BooleanSearchFilter.build_query(filters.version_name, version_expr))
        else:
            stmt = stmt.where(version_expr.ilike(filters.version_name))

    # --- Tag filters (with BooleanSearchFilter) ---
    tag_conditions = []
    if filters.tag_name is not None:
        if filters.advanced_search:
            tag_conditions.append(
                BooleanSearchFilter.build_array_filter(
                    filters.tag_name, func.avals(OutputDetailVersion.tags)
                )
            )
        else:
            tag_conditions.append(
                literal(filters.tag_name).ilike(any_(func.avals(OutputDetailVersion.tags)))
            )

    if filters.tag_id__in:
        tag_conditions.append(
            func.coalesce(func.akeys(OutputDetailVersion.tags), []).op("&&")(
                [str(id) for id in filters.tag_id__in]
            )
        )

    # Combine both filters if both provided
    if tag_conditions:
        stmt = stmt.where(and_(*tag_conditions))
    # --- File existence filters ---
    file_filters = {
        filters.file_exists: OutputDetail.file_path,
        filters.converted_file_exists: OutputDetail.converted_file_path,
    }
    for condition, column in file_filters.items():
        if condition is not None:
            stmt = stmt.where(
                column.isnot(None)
                if condition else column.is_(None))
    # --- Outdated outputs filter ---
    if filters.outdated_outputs is not None:
        source_id = filters.source_id
        source_name = None

        if source_id:
            # Fetch actual source name from DB
            result = await session.execute(
                select(
                    Source.name
                ).where(
                    Source.id == source_id
                    )
                )
            source_name = result.scalar_one_or_none()
        elif filters.source_name:
            source_name = filters.source_name
        else:
            source_name = settings.default_source

        if source_name is None:
            raise HTTPException(
                status_code=404,
                detail="Source not found."
            )

        if source_name.lower() == "docs":
            raise HTTPException(
                status_code=400,
                detail="The sync filter is not available for DOCS."
            )
        stmt = stmt.where(
            OutputDetail.is_out_of_sync.is_(
                filters.outdated_outputs
                )
            )
    # --- docs_shared_as filter ---
    # Behavior: if docs_shared_as value is Yes -> return PREPROD records
    #           if docs_shared_as value is no -> return PROD and NULL records
    if filters.docs_shared_as is not None:
        if filters.docs_shared_as.lower() == "yes":
            stmt = stmt.where(OutputDetail.docs_shared_as == "PREPROD")
        else:
            stmt = stmt.where(
                (OutputDetail.docs_shared_as == "PROD")
                | (OutputDetail.docs_shared_as.is_(None))
            )
    return stmt
