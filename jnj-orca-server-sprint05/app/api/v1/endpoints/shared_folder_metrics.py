"""
 API endpoints for shared folder metrics.
"""
from io import BytesIO
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
import pandas as pd

from app.core.db import get_session
from app.models.shared_folder_metrics import SharedFolderMetric

router = APIRouter()


@router.get("/shared-folder-metrics", response_class=StreamingResponse)
async def export_shared_folder_metrics_xlsx(
    db: AsyncSession = Depends(get_session)
):
    """
    Export shared folder metrics as an Excel file (.xlsx) with consistent column order.
    """
    result = await db.execute(select(SharedFolderMetric))
    metrics = result.scalars().all()

    if not metrics:
        df = pd.DataFrame(columns=["No data"])
    else:
        # Convert ORM objects → list of dicts
        df = pd.DataFrame([metric.dict() for metric in metrics])

        # Adjust this list to match your logical field order in reports
        ordered_columns = [
            "id",
            "tag_id",
            "tag_name",
            "file_shared_by",
            "file_shared_to",
            "file_shared_from_ts",
            "file_shared_to_ts",
            "comment",
            "output_detail_id",
            "compound",
            "study",
            "dbr",
            "re",
            "file_shared",
            "file_name",
            "file_version_major",
            "file_version_minor",
            "file_version_patch",
        ]

        # Keep only available columns, in defined order
        df = df[[column for column in ordered_columns if column in df.columns]]

        # Excel doesn’t support timezone-aware datetimes
        for col in df.select_dtypes(include=["datetimetz"]).columns:
            df[col] = df[col].dt.tz_convert(None)

        # Handle any datetime objects with tzinfo
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].apply(
                    lambda time_zone: time_zone.replace(
                        tzinfo=None
                        ) if hasattr(
                            time_zone,
                            "tzinfo"
                            ) and time_zone.tzinfo else time_zone
                )

    # Write to Excel in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SharedFolderMetrics")

    output.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="shared_folder_metrics.xlsx"'
    }

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
