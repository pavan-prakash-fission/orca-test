"""
Sync versioned files from Lustre REPO to S3 with proper authentication.
Supports both single and bulk operations.
"""

import re
import subprocess
import mimetypes
import time
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.output_detail import OutputDetail
from app.utils.s3_boto_client import get_s3_client

# Configuration
DEFAULT_LUSTRE_PATH = Path(settings.lustre_base_path)
ORCAUSER_NAME = settings.lustre_user
ORCAUSER_PASSWORD = settings.lustre_user_password
BUCKET = settings.bucket

# Logger setup
logger = logging.getLogger(__name__)


# ----------------- Lustre Access Helper -----------------
def run_lustre_command(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """
    Run command as orcauser with sudo, auto-entering password.
    
    Args:
        cmd: Command as list of strings
        timeout: Command timeout in seconds
    
    Returns:
        Tuple of (returncode, stdout, stderr)
    
    Note:
        'test' command is a standard Unix/Linux shell command (not Lustre-specific).
        It evaluates conditional expressions like file existence, type checks, etc.
        Examples: test -e (exists), test -f (is file), test -d (is directory)
    """
    # Build command string
    cmd_str = ' '.join([f"'{c}'" if ' ' in c else c for c in cmd])

    # Shell script that auto-enters password for both sudo calls
    shell_script = f"""
echo '{ORCAUSER_PASSWORD}' | sudo -S -u {ORCAUSER_NAME} bash -c "echo '{ORCAUSER_PASSWORD}' | sudo -S {cmd_str}"
"""
    
    process = None
    try:
        process = subprocess.Popen(
            shell_script,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = process.communicate(timeout=timeout)
        
        # Decode output
        stdout = stdout.decode()
        stderr = stderr.decode()
        
        # Remove sudo prompts from stderr
        stderr_clean = '\n'.join([
            line for line in stderr.split('\n')
            if not line.startswith('[sudo]') and line.strip()
        ])
        
        return process.returncode, stdout, stderr_clean
    
    except subprocess.TimeoutExpired:
        if process:
            process.kill()
            process.wait()
        return -1, "", "Command timed out"
    except Exception as e:
        if process:
            try:
                process.kill()
                process.wait()
            except Exception:
                pass
        return -1, "", str(e)


def lustre_path_exists(path: Path) -> bool:
    """Check if path exists on Lustre using 'test -e' command."""
    returncode, _, _ = run_lustre_command(['test', '-e', str(path)])
    return returncode == 0


def lustre_is_file(path: Path) -> bool:
    """Check if path is a file on Lustre using 'test -f' command."""
    returncode, _, _ = run_lustre_command(['test', '-f', str(path)])
    return returncode == 0


def lustre_is_dir(path: Path) -> bool:
    """Check if path is a directory on Lustre using 'test -d' command."""
    returncode, _, _ = run_lustre_command(['test', '-d', str(path)])
    return returncode == 0


def lustre_list_dir(path: Path) -> List[Path]:
    """List directory contents on Lustre."""
    returncode, stdout, stderr = run_lustre_command(['ls', '-1', str(path)])
    
    if returncode != 0:
        logger.error(f"Error listing directory {path}: {stderr}")
        return []
    
    entries = stdout.strip().split('\n')
    return [Path(str(path) + '/' + entry) for entry in entries if entry]


def lustre_copy_to_s3(source: Path, bucket: str, s3_key: str, retries: int = 1, timeout: int = 300) -> Tuple[bool, Optional[str]]:
    """
    Stream a Lustre file directly to S3 without creating a temporary local copy.
    Uses existing helpers for existence/type checks, then streams 'cat' output
    from a subprocess into boto3.upload_fileobj().

    Args:
        source: Source file path on Lustre
        bucket: S3 bucket name
        s3_key: S3 object key
        retries: number of retries after first failure (default 1 -> 2 attempts total)
        timeout: maximum seconds to wait for the subprocess to finish after streaming

    Returns:
        (success, error_message)
    """
    s3_client = get_s3_client()
    content_type = mimetypes.guess_type(str(source))[0] or "binary/octet-stream"
    extra_args = {"ContentType": content_type}

    last_error = None
    attempts = retries + 1

    for attempt in range(1, attempts + 1):
        process = None
        try:
            cmd_str = f"cat '{source}'"
            shell_script = (
                f"echo '{ORCAUSER_PASSWORD}' | sudo -S -u {ORCAUSER_NAME} bash -c "
                f"\"echo '{ORCAUSER_PASSWORD}' | sudo -S {cmd_str}\""
            )

            process = subprocess.Popen(
                shell_script,
                shell=True,
                stdout=subprocess.PIPE,    # binary stream
                stderr=subprocess.PIPE
            )

            # Stream stdout directly into S3
            s3_client.upload_fileobj(process.stdout, bucket, s3_key, ExtraArgs=extra_args)

            # Wait for subprocess to finish
            _, stderr = process.communicate(timeout=timeout)
            stderr_text = stderr.decode().strip() if isinstance(stderr, (bytes, bytearray)) else str(stderr).strip()

            if process.returncode != 0:
                last_error = f"Lustre read failed (returncode={process.returncode}): {stderr_text}"
            else:
                return True, None

        except subprocess.TimeoutExpired:
            last_error = "Lustre read timed out"
            if process:
                try:
                    process.kill()
                    process.wait()
                except Exception:
                    pass

        except Exception as e:
            last_error = f"Direct upload failed: {str(e)}"
            if process:
                try:
                    process.kill()
                    process.wait()
                except Exception:
                    pass

        # Retry delay
        if attempt < attempts:
            time.sleep(1)

    return False, last_error or "Unknown error during Lustre->S3 streaming"


def lustre_get_file_size(path: Path) -> Optional[float]:
    """Get file size from Lustre using 'stat -c %s' command."""
    returncode, stdout, _ = run_lustre_command(['stat', '-c', '%s', str(path)])
    
    if returncode != 0:
        return None
    
    try:
        return float(stdout.strip())
    except ValueError:
        return None


# ----------------- Version Parsing Helpers -----------------
def parse_version_from_filename(name: str) -> Optional[Tuple[int, int]]:
    """
    Find a trailing _@@MAJ.MIN in the filename and return (MAJ, MIN).
    Only valid format: test5.rtf_@@2.0
    
    Args:
        name: Filename to parse
    
    Returns:
        Tuple of (major, minor) version numbers or None
    """
    m = re.search(r'_@@(\d+)\.(\d+)$', name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def original_from_versioned(name: str) -> str:
    """
    Convert a versioned filename to the original filename.
    Only handles format: "test5.rtf_@@2.0" -> "test5.rtf"
    
    Args:
        name: Versioned filename
    
    Returns:
        Original filename without version suffix
    """
    if not parse_version_from_filename(name):
        return name
    
    return name.split('_@@')[0]


def version_key(version_str: str) -> Tuple[int, int]:
    """
    Parse version string to tuple for comparison.
    Default version is 1.0 (not 0.0).
    
    Args:
        version_str: Version string like "2.0" or "1.5"
    
    Returns:
        Tuple of (major, minor) for comparison
    """
    parts = version_str.split(".")
    major = int(parts[0]) if parts and parts[0].isdigit() else 1
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return major, minor


# ----------------- Business Logic Functions -----------------
def resolve_repo_versions_path(adr_filepath: str) -> Optional[Path]:
    """
    Resolve the REPO .versions directory path from an ADR filepath.

    Returns the Path to the .versions directory (NOT including the pillar).
    Example returned value:
      /lustre/shared/adr/REPO/pharma/testcompound02/study_c012/dbr_c013/re_c013/output/.versions

    Returns None if it can't be resolved (e.g. path not under pharma or missing pillar).
    """
    # Map /adr/<...> to Lustre path
    if adr_filepath.startswith("/adr/"):
        lustre_fp = Path(str(DEFAULT_LUSTRE_PATH) + '/' + adr_filepath[len("/adr/"):])
    else:
        lustre_fp = Path(adr_filepath)

    # Validate that path includes 'pharma' and 'output' and pillar
    try:
        parts = list(lustre_fp.parts)
        idx_pharma = parts.index("pharma")
        idx_output = parts.index("output")
    except ValueError:
        return None

    # Confirm there's a pillar (PROD/PREPROD) earlier in the path
    source_pillar = None
    for i in range(idx_pharma - 1, -1, -1):
        if parts[i] in ("PROD", "PREPROD"):
            source_pillar = parts[i]
            break
    if not source_pillar:
        return None

    # Build .versions parent path (without the pillar)
    # Example: /lustre/shared/adr/REPO/pharma/.../output/.versions
    path_up_to_output = parts[idx_pharma: idx_output + 1]  # pharma/.../output
    repo_versions_parent = Path(
        str(DEFAULT_LUSTRE_PATH) + '/REPO/' + '/'.join(path_up_to_output) + '/.versions'
    )
    return repo_versions_parent


def find_latest_version_file(
    repo_versions_base: Path,
    original_filename: str
) -> Optional[Tuple[Path, str]]:
    """
    Find the latest version file in REPO .versions directory.

    This function accepts either:
      - repo_versions_base pointing to .versions (containing pillar dirs), OR
      - repo_versions_base pointing to .versions/<PILLAR> (directly the pillar)

    Returns: (Path to versioned file, version_string) or None
    """
    # Normalize input: if caller passed a tuple string by mistake, fail fast
    if not isinstance(repo_versions_base, Path):
        logger.error(f"repo_versions_base must be a Path object {repo_versions_base}")
        return None, f"repo_versions_base must be a Path object {repo_versions_base}"

    # If path doesn't exist at all, bail out
    if not lustre_path_exists(repo_versions_base):
        logger.warning(f"REPO .versions path does not exist: {repo_versions_base}")
        return None, f"REPO .versions path does not exist: {repo_versions_base}"

    candidates: List[Tuple[Path, str]] = []

    try:
        # Determine whether repo_versions_base is a pillar folder (ends with PROD/PREPROD)
        last_part = repo_versions_base.name.upper()
        if last_part in ("PROD", "PREPROD"):
            # repo_versions_base points directly to the pillar folder; read files inside it
            pillar_dirs = [repo_versions_base]
        else:
            # repo_versions_base should contain pillar subdirectories (PROD, PREPROD)
            # list children and treat directories as pillars
            pillar_dirs = []
            for child in lustre_list_dir(repo_versions_base):
                if lustre_is_dir(child):
                    pillar_dirs.append(child)

        # Iterate pillars and collect matching versioned files
        for pillar_dir in pillar_dirs:
            for f in lustre_list_dir(pillar_dir):
                # f is a Path like /.../.versions/PROD/pro7.rtf_@@2.0
                if not lustre_is_file(f):
                    continue

                cand_orig = original_from_versioned(f.name)
                if cand_orig != original_filename:
                    continue

                pv = parse_version_from_filename(f.name)
                if not pv:
                    continue

                ver_str = f"{pv[0]}.{pv[1]}"
                candidates.append((f, ver_str))

    except Exception as e:
        logger.error(f"Error finding versioned files in {repo_versions_base}: {e}")
        return None, f"Error finding versioned files in {repo_versions_base}: {e}"

    if not candidates:
        return None, f"No versioned files found for {original_filename} for path {repo_versions_base}"

    # Return the candidate with the highest version
    candidates_sorted = sorted(candidates, key=lambda it: version_key(it[1]))
    return candidates_sorted[-1]


async def update_output_detail_record(
    session: AsyncSession,
    output_detail: OutputDetail,
    new_version: str,
    file_size: Optional[float],
    max_retries: int = 3
) -> bool:
    """
    Update OutputDetail record with new version information.
    Retries up to max_retries times on failure.
    
    Args:
        session: Database session
        output_detail: OutputDetail instance to update
        new_version: New version string
        file_size: File size in bytes
        max_retries: Maximum number of retry attempts
    
    Returns:
        bool: True if successful, False otherwise
    """
    for attempt in range(1, max_retries + 1):
        try:
            output_detail.space_version = new_version
            output_detail.orca_version = new_version
            output_detail.is_out_of_sync = False
            
            if file_size is not None:
                output_detail.file_size = file_size

            await session.flush()
            await session.commit()
            
            logger.info(f"Successfully updated OutputDetail id={output_detail.id} to version {new_version}")
            return True
        
        except Exception as e:
            logger.warning(f"DB update attempt {attempt}/{max_retries} failed for id={output_detail.id}: {e}")
            
            if attempt < max_retries:
                await session.rollback()
                time.sleep(0.5)  # Brief delay before retry
            else:
                logger.error(f"DB update failed after {max_retries} attempts for id={output_detail.id}")
                await session.rollback()
                return False
    
    return False


# ----------------- Main Sync Function -----------------
async def update_latest_version_to_s3(
    session: AsyncSession,
    output_detail_id: int,
    bucket: str
) -> dict:
    """
    Sync the latest version of a file from Lustre REPO to S3.
    
    Process:
      1. Fetch OutputDetail from database
      2. Resolve REPO .versions path from adr_filepath
      3. Find the highest version file
      4. Copy file directly from Lustre to S3
      5. Update database record
    
    Args:
        session: Database session
        output_detail_id: OutputDetail ID to sync
        bucket: S3 bucket name
    
    Returns:
        Dict with sync result details
    """
    result = {
        'id': output_detail_id,
        'identifier': None,
        'success': False,
        'message': '',
        'old_version': None,
        'new_version': None
    }
    
    # Step 1: Fetch OutputDetail
    stmt = select(OutputDetail).where(OutputDetail.id == output_detail_id)
    res = await session.execute(stmt)
    od = res.scalars().first()
    
    if not od:
        result['message'] = f"OutputDetail id={output_detail_id} not found"
        logger.error(result['message'])
        return result

    result['identifier'] = od.identifier
    result['old_version'] = od.space_version

    if not od.adr_filepath:
        result['message'] = f"No adr_filepath for id={output_detail_id}"
        logger.error(result['message'])
        return result

    # Step 2: Resolve REPO .versions path
    repo_versions_base = resolve_repo_versions_path(od.adr_filepath)
    
    if not repo_versions_base:
        result['message'] = "Could not resolve REPO .versions path"
        logger.error(result['message'])
        return result

    logger.info(f"Resolved versions path: {repo_versions_base} for id={output_detail_id}")

    # Step 3: Find latest version file
    original_filename = Path(od.adr_filepath).name
    chosen_file, error_or_version = find_latest_version_file(
        repo_versions_base=repo_versions_base,
        original_filename=original_filename
    )
    
    if not chosen_file:
        result['message'] = f"No versioned files found: {error_or_version}"
        logger.warning(result['message'])
        return result

    chosen_ver = error_or_version
    result['new_version'] = chosen_ver
    
    logger.info(f"Chosen file: {chosen_file} (version {chosen_ver}) for id={output_detail_id}")

    # Step 4: Copy file from Lustre to S3
    if not od.file_path:
        result['message'] = f"OutputDetail.file_path is empty for id={od.id}"
        logger.error(result['message'])
        return result

    success, error_msg = lustre_copy_to_s3(
        source=chosen_file,
        bucket=bucket,
        s3_key=od.file_path
    )
    
    if not success:
        result['message'] = error_msg
        logger.error(f"S3 upload failed for id={output_detail_id}: {error_msg}")
        return result

    logger.info(f"Uploaded to S3: bucket='{bucket}', key='{od.file_path}'")

    # Step 5: Update database record
    file_size = lustre_get_file_size(chosen_file)
    
    db_success = await update_output_detail_record(
        session=session,
        output_detail=od,
        new_version=chosen_ver,
        file_size=file_size
    )
    
    if not db_success:
        result['message'] = f"DB update failed after retries"
        logger.error(result['message'])
        return result

    result['success'] = True
    result['message'] = f"Successfully synced to version {chosen_ver}"
    logger.info(f"Sync completed for id={output_detail_id}")
    
    return result


async def update_multiple_versions_to_s3(
    session: AsyncSession,
    output_detail_ids: List[int]
) -> dict:
    """
    Sync multiple files in bulk.
    
    Args:
        session: Database session
        output_detail_ids: List of OutputDetail IDs to sync
    
    Returns:
        Dict with overall results
    """
    results = {
        'synced_count': 0,
        'failed_count': 0,
        'details': []
    }
    
    logger.info(f"Starting bulk sync for {len(output_detail_ids)} files")
    
    for output_id in output_detail_ids:
        result = await update_latest_version_to_s3(
            session=session,
            output_detail_id=output_id,
            bucket=BUCKET
        )
        
        results['details'].append(result)
        
        if result['success']:
            results['synced_count'] += 1
        else:
            results['failed_count'] += 1
    
    logger.info(f"Bulk sync completed: {results['synced_count']} succeeded, {results['failed_count']} failed")
    
    return results