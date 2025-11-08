"""
Endpoint to download watermarked files, either as single files or zipped batches using FastAPI and Celery.
"""

import os
import asyncio
import uuid
import shutil
import zipstream
import logging
import mimetypes
import zipfile

from fastapi import HTTPException, BackgroundTasks, APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse
from celery.result import AsyncResult
from celery import chord, group
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy import cast, String

from app.schemas.download import InputFileBatch, TaggedOutputs
from app.schemas.download import InputFileBatch
from app.celery_worker import celery_app
from app.utils import add_watermark as aw
from app.models import OutputDetail, OutputDetailVersion
from app.models import DatabaseReleaseTag
from app.core.db import get_session
from app.utils.s3_boto_client import get_s3_client, download_s3_files
from app.config. settings import settings
from app.utils.authorization import authorize_user
from app.utils.authorize_reviewer import authorize_reviewer


router = APIRouter()
logger = logging.getLogger(__name__)

# Mapping of extensions to handler functions
EXTENSION_HANDLERS = {
    "pdf": aw.add_watermark_to_pdf,
    "docx": aw.add_watermark_to_docx,
    "doc": aw.add_watermark_to_docx,
    "jpg": aw.add_watermark_to_image,
    "jpeg": aw.add_watermark_to_image,
    "png": aw.add_watermark_to_image,
    "rtf": aw.add_watermark_to_rtf,
    "csv": aw.add_watermark_to_csv,
    "svg": aw.add_watermark_to_svg,
    "pptx": aw.add_watermark_to_pptx,
    "ppt": aw.add_watermark_to_pptx,
}

def cleanup_file(file_path: str, zipped:bool, task_id: str = None):
    
    """
    Deletes a file.
    """
    
    try:
        # input folder cleanup
        shutil.rmtree(f"{settings.s3_local_path}/{task_id}")
        
        # output file cleanup
        if not zipped:
            directory = os.path.dirname(file_path)
            os.remove(file_path)
            os.rmdir(directory)
        else:
            os.remove(file_path)
    except OSError:
        raise ValueError("Permission Denied or file does not exist.")
    except Exception:
        raise HTTPException(status_code=500, detail="Error deleting file in the server.")

async def add_watermark_batch(files:dict, session, is_reviewer: bool = False) -> dict:
    
    """
    - Initiates watermarking for a list of files and zips the output.
    - Orchestrates PARALLEL watermarking for a batch of files using a Celery Chord.
    Params:
        - file_paths: List of file paths to be watermarked.
    Returns:
        - task_id: ID of the Celery task for tracking.
    """
    
    file_ids = files.file_ids
    source = files.source

    # get the file paths, docs_shared_as, source_name from the output_details table
    files = files.model_dump()
    query = select(OutputDetail.file_path, OutputDetail.docs_shared_as, OutputDetail.source_name).where(OutputDetail.id.in_(file_ids))
    results = await session.execute(query)
    file_rows = results.all()
    s3_file_paths = [row.file_path for row in file_rows]
    docs_sources = [row.docs_shared_as for row in file_rows]
    sources = [row.source_name for row in file_rows]

    # download the files from s3 to server
    job_id = str(uuid.uuid4())
    s3_client = get_s3_client()
    status, file_paths = download_s3_files(s3_client, s3_file_paths, local_dir= f"{settings.s3_local_path}/{job_id}")
    if not status:
        raise HTTPException(status_code=500, deetail= f"Error downloading files from S3 {status}.")

    output_dir = f"output/{job_id}"
    os.makedirs(output_dir, exist_ok=True)

    # Pair each file_path with its docs_source
    file_path_to_docs_source = dict(zip(file_paths, docs_sources))

    # Pair each file_path with its source_name
    file_path_to_source_name = dict(zip(file_paths, sources))
    if is_reviewer:
        header = group(
            process_single_file.s(path, file_path_to_source_name.get(path), output_dir, file_path_to_docs_source.get(path)) for path in file_paths
        )
    else:
        header = group(
            process_single_file.s(path, source, output_dir, file_path_to_docs_source.get(path)) for path in file_paths
        )
    callback = zip_and_cleanup.s(task_id=job_id)
    chord_result = chord(header)(callback)
    
    return {"message": "Batch watermarking and zipping initiated.", "task_id": chord_result.id, "job_id": job_id}     

def process_preprod_file(file_path, output_dir):
    
    """Handle watermarking for PREPROD files."""
    
    ext = file_path.lower().split('.')[-1]
    file_name = os.path.basename(file_path).split('.')[0]

    if ext == "csv":
        output_file = f"{file_name}-DRAFT.pdf"
    else:
        output_file = f"{file_name}-DRAFT.{ext}"
    output_path = os.path.join(output_dir, output_file)

    watermark_enabled = settings.is_watermark_enabled
    if watermark_enabled:
        handler = EXTENSION_HANDLERS.get(ext)
        if handler:
            handler(file_path, output_path)  # Apply watermark
            return output_path
        return None
    else:
        shutil.copy(file_path, output_path)
        return output_path

def process_prod_file(file_path, output_dir):
    
    """Handle copying for PROD files (no watermark)."""
    
    output_path = os.path.join(output_dir, os.path.basename(file_path))
    shutil.copy(file_path, output_path)
    return output_path

@celery_app.task
def process_single_file(file_path: str, source: str, output_dir: str, docs_shared_as) -> str:
    
    """
    Celery task to process ONE file. This will run in parallel for each file.
    """
    
    if source == "PREPROD":
        return process_preprod_file(file_path, output_dir)
    elif source == "PROD":
        return process_prod_file(file_path, output_dir)
    elif source == "DOCS":
        if docs_shared_as == "PROD" or docs_shared_as is None:
            return process_prod_file(file_path, output_dir)
        elif docs_shared_as == "PREPROD":
            return process_preprod_file(file_path, output_dir)
        else:
            raise ValueError(f"Unexpected docs_shared_as value: {docs_shared_as}")

@celery_app.task(bind=True)
def zip_and_cleanup(self, processed_files: list, task_id: str) -> tuple:
    """
    Celery task to zip results. This is the chord callback, running ONCE after all
    process_single_file tasks are complete.
    """
    valid_files = [path for path in processed_files if path]
    output_dir = f"output/{task_id}"

    if not valid_files:
        raise ValueError("No files were successfully processed.")

    if len(valid_files) == 1:
        return (valid_files[0], False)

    zip_output_path = f"output/{task_id}"
    shutil.make_archive(zip_output_path, "zip", output_dir)
    shutil.rmtree(output_dir)

    return (f"{zip_output_path}.zip", True)

async def get_context_info(compound_name: str, study_name: str, dbr_name: str, session: AsyncSession):
    """
    Retrieves context information for the given compound, study, and database release IDs.
    """
    context_query = select(
        OutputDetail.source_name,
        OutputDetail.compound_name,
        OutputDetail.study_name,
        OutputDetail.database_release_name
    ).where(
        OutputDetail.compound_name == compound_name,
        OutputDetail.study_name == study_name,
        OutputDetail.database_release_name == dbr_name,
    ).limit(1)

    context_result = await session.execute(context_query)
    context_row = context_result.one_or_none()
    if not context_row:
        raise HTTPException(
            status_code=404,
            detail="Confirm with the Statistical Programmer the correct compound, study, database release"
        )
    return context_row

async def validate_tag_name(tag_name: str, compound_name: str, study_name: str, dbr_name: str, session: AsyncSession):
    """
    Validates the existence of a tag by its ID.
    """
    tag_query = select(DatabaseReleaseTag.tag_name).where(DatabaseReleaseTag.tag_name == tag_name)
    tag_result = await session.execute(tag_query)
    tag_row = tag_result.one_or_none()
    if not tag_row:
        raise HTTPException(
            status_code=404,
            detail=f"Confirm with the Statistical Programmer the correct Tag for {compound_name}/{study_name}/{dbr_name}"
        )
    return tag_row[0]

@router.post("/")
async def download(files: InputFileBatch, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session), current_user=Depends(authorize_user)):
    """
    Download watermarked file(s).

    - Single file → return directly.
    - Multiple files → return as a ZIP.
    - Cleans up temporary files after download.
    """
    try:
        is_reviewer = current_user.role.lower() == "reviewer"
        if is_reviewer:
            await authorize_reviewer(current_user, files.file_ids, session)

        if not files.file_ids:
            raise HTTPException(status_code=400, detail="No file paths provided.")

        wrapper_result = await add_watermark_batch(files, session, is_reviewer=is_reviewer)
        task_id = wrapper_result["task_id"]
        task_result = AsyncResult(task_id, app=celery_app)
        while not task_result.ready():
            await asyncio.sleep(1)

        if not task_result.successful():
            raise HTTPException(status_code=500, detail=f"Task failed: {task_result.info}")

        file_path, zipped = task_result.result
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found.")
        
        background_tasks.add_task(cleanup_file, file_path, zipped, wrapper_result["job_id"])
        if not zipped:
            file_name = os.path.basename(file_path)
            headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
            return FileResponse(path=file_path, headers=headers, media_type="application/octet-stream")

        if files.source == "PROD":
            file_name = settings.prod_zip_name
        elif files.source == "PREPROD" or files.source is None:
            file_name = settings.preprod_zip_name
        elif files.source == "DOCS":
            file_name = settings.docs_zip_name
        
        headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
        return FileResponse(path=file_path, headers=headers, media_type="application/zip")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.exception("Error download %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stream")
async def download_zip_file_stream(files: InputFileBatch, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    """
    Streams the watermarked file(s).
    - If single file → stream directly
    - If multiple files → stream a zip
    """

    if not files.file_ids:
        raise HTTPException(status_code=400, detail="No file paths provided.")

    # Trigger watermark batch task
    wrapper_result = await add_watermark_batch(files, session)
    task_id = wrapper_result["task_id"]

    task_result = AsyncResult(task_id, app=celery_app)
    while not task_result.ready():
        await asyncio.sleep(1)

    if not task_result.successful():
        raise HTTPException(status_code=500, detail=f"Task failed: {task_result.info}")

    file_path, zipped = task_result.result
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    # Schedule cleanup after response
    background_tasks.add_task(cleanup_file, file_path, zipped)

    if not zipped:
        # Single file → stream directly
        file_name = os.path.basename(file_path)
        headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}

        def iterfile(path: str):
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    yield chunk

        return StreamingResponse(iterfile(file_path),
                                 headers=headers,
                                 media_type="application/octet-stream")

    # Multiple files → stream as zip
    z = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_DEFLATED)
    z.write(file_path, arcname="draft_files.zip")

    headers = {"Content-Disposition": 'attachment; filename="draft_files.zip"'}
    return StreamingResponse(z, headers=headers, media_type="application/zip")

@router.post("/tagged/files")
async def download_tagged_files(files: TaggedOutputs, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    """
    Download the tagged files as a zip based on compound_id, study_id, dbr_id, tag_id, and optional file_name.
    """
    try:
        # Get context information
        source_name, compound_name, study_name, dbr_name = await get_context_info(files.compound_name, files.study_name, files.dbr_name, session)

        # Validate tag name
        tag_name = await validate_tag_name(files.tag_name, compound_name, study_name, dbr_name, session)

        columns = [
            OutputDetail.id,
            OutputDetail.source_name,
            OutputDetail.compound_name,
            OutputDetail.study_name,
            OutputDetail.database_release_name,
            OutputDetail.reporting_effort_name,
            OutputDetailVersion.tags,
            OutputDetail.file_type,
            OutputDetail.identifier
        ]

        filters = [
            OutputDetail.compound_name == files.compound_name,
            OutputDetail.study_name == files.study_name,
            OutputDetail.database_release_name == files.dbr_name,
            cast(OutputDetailVersion.tags, String).ilike(f"%{files.tag_name}%")
        ]

        if getattr(files, "source_name", None):
            filters.insert(0, OutputDetail.source_name == files.source_name)

        tag_query = select(*columns).join(OutputDetailVersion, OutputDetail.id == OutputDetailVersion.output_id).where(*filters)

        if files.file_name:
            escaped_file_name = files.file_name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            tag_query = tag_query.where(OutputDetail.identifier.ilike(f"%{escaped_file_name}%"))

        results = await session.execute(tag_query)
        rows = results.all()


        if files.file_name and len(rows) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"The file '{files.file_name}' is not in Tag '{tag_name}' for {compound_name}/{study_name}/{dbr_name}"
            )
        elif files.file_name and len(rows) > 1:
            file_names = [f"{row.identifier}.{row.file_type}" for row in rows]
            raise HTTPException(
                status_code=400,
                detail=f'The file "{files.file_name}" matches multiple files in Tag "{tag_name}" for {compound_name}/{study_name}/{dbr_name}: {", ".join(file_names)}'
            )

        file_ids = [row.id for row in rows]
        input_batch = InputFileBatch(file_ids=file_ids, source=source_name)
        wrapper_result = await add_watermark_batch(input_batch, session)
        task_id = wrapper_result["task_id"]
        task_result = AsyncResult(task_id, app=celery_app)
        
        timeout = 300
        elapsed = 0
        while not task_result.ready():
            if elapsed >= timeout:
                raise HTTPException(status_code=504, detail="The request timed out while processing the files.")
            await asyncio.sleep(1)
            elapsed += 1

        if not task_result.successful():
            raise HTTPException(status_code=500, detail=f"Task failed: {task_result.info}")

        file_path, zipped = task_result.result
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found.")

        background_tasks.add_task(cleanup_file, file_path, zipped, wrapper_result["job_id"])

        file_name = f"{tag_name}_outputs.zip"
        if file_path.endswith('.zip'):
            headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
            return FileResponse(path=file_path, headers=headers, media_type="application/zip")
        else:
            zip_path = f"output/{file_path.split('/')[1]}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(file_path, arcname=os.path.basename(file_path))
            headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
            return FileResponse(
                path=zip_path, 
                headers=headers, 
                media_type="application/zip"
            )
    except Exception as e:
        logger.exception("Error downloading tagged files: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
