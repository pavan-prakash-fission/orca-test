import boto3
import os
from app.config.settings import settings
from typing import Tuple

def get_s3_client():   
    """
    Create an S3 client with credentials.
    """
    session = boto3.session.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.region,
    )
    s3_client=  session.client("s3")
    return s3_client

def download_s3_files(
    s3_client,
    s3_file_paths: list[str],
    local_dir: str = settings.s3_local_path
) -> Tuple[bool, list[str]]:
    """
    Download multiple files from S3 into the given folder.
    Keeps original filenames and extensions.

    Returns:
        (success: bool, downloaded_files: list[str])
    """
    os.makedirs(local_dir, exist_ok=True)

    downloaded_files = []
    success = True

    for s3_file_path in s3_file_paths:
        try:
            # Extract filename from S3 key
            filename = os.path.basename(s3_file_path)
            local_path = os.path.join(local_dir, filename)

            # Download file
            s3_client.download_file(settings.bucket, s3_file_path, local_path)

            downloaded_files.append(local_path)

        except Exception:
            success = False
            raise

    return success, downloaded_files


def generate_presigned_url(file_path):
    """
    Generate a pre-signed URL for an S3 object.

    Args:
        file_path (str): The S3 key (path) for the file.

    Returns:
        str: A pre-signed URL for the file or None if an error occurs.
    """
    try:
        s3_client = get_s3_client()
        bucket_name = settings.bucket

        # Generate the pre-signed URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': file_path},
            ExpiresIn=3600,  # URL expires in 1 hour
        )
        return presigned_url
    except Exception:
        # logger.error(f"Error generating pre-signed URL for {file_path}: {e}")
        return None

