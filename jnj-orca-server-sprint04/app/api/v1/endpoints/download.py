"""
Endpoint to download watermarked files, either as single files or zipped batches using FastAPI and Celery.
"""

import os
import asyncio
import uuid
import shutil
import zipstream
import logging

from fastapi import HTTPException, BackgroundTasks, APIRouter, Depends
from fastapi.responses import FileResponse, StreamingResponse
from celery.result import AsyncResult
from celery import chord, group
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.schemas.download import InputFileBatch
from app.celery_worker import celery_app
from app.utils import add_watermark as aw
from app.models import OutputDetail
from app.core.db import get_session
from app.utils.s3_boto_client import get_s3_client, download_s3_files
from app.config. settings import settings


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

async def add_watermark_batch(files:dict, session):
    
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

    # get the file paths from the output_details table
    files = files.model_dump()
    query = select(OutputDetail.file_path).where(OutputDetail.id.in_(file_ids))
    results = await session.execute(query)
    s3_file_paths = results.scalars().all()

    # download the files from s3 to server
    job_id = str(uuid.uuid4())
    s3_client = get_s3_client()
    status, file_paths = download_s3_files(s3_client, s3_file_paths, local_dir= f"{settings.s3_local_path}/{job_id}")
    if not status:
        raise HTTPException(status_code=500, deetail= f"Error downloading files from S3 {status}.")
    
    
    output_dir = f"output/{job_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    header = group(
        process_single_file.s(path, source, output_dir) for path in file_paths
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
def process_single_file(file_path: str, source: str, output_dir: str) -> str:
    
    """
    Celery task to process ONE file. This will run in parallel for each file.
    """
    
    if source == "PREPROD":
        return process_preprod_file(file_path, output_dir)
    elif source == "PROD":
        return process_prod_file(file_path, output_dir)

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

@router.post("/")
async def download(files: InputFileBatch, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)):
    """
    Download watermarked file(s).

    - Single file → return directly.
    - Multiple files → return as a ZIP.
    - Cleans up temporary files after download.
    """
    try:
        if not files.file_ids:
            raise HTTPException(status_code=400, detail="No file paths provided.")

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
        
        background_tasks.add_task(cleanup_file, file_path, zipped, wrapper_result["job_id"])
        if not zipped:
            file_name = os.path.basename(file_path)
            headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
            return FileResponse(path=file_path, headers=headers, media_type="application/octet-stream")

        if files.source == "PROD":
            file_name = settings.prod_zip_name
        elif files.source == "PREPROD":
            file_name = settings.preprod_zip_name
        
        headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
        return FileResponse(path=file_path, headers=headers, media_type="application/zip")
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
