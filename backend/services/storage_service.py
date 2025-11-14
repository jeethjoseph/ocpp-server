"""
Firmware Storage Service
Handles local filesystem storage for firmware files
"""

import os
import hashlib
from typing import BinaryIO
from fastapi import UploadFile

# Get the base directory for firmware storage
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE_DIR = os.path.join(BASE_DIR, "firmware_files")

# Ensure firmware directory exists
os.makedirs(FIRMWARE_DIR, exist_ok=True)


def calculate_checksum(file_path: str) -> str:
    """
    Calculate MD5 checksum of a file

    Args:
        file_path: Path to the file

    Returns:
        MD5 checksum as hex string
    """
    md5_hash = hashlib.md5()

    with open(file_path, "rb") as f:
        # Read file in chunks to handle large files
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)

    return md5_hash.hexdigest()


def calculate_checksum_from_bytes(file_content: bytes) -> str:
    """
    Calculate MD5 checksum from bytes

    Args:
        file_content: File content as bytes

    Returns:
        MD5 checksum as hex string
    """
    md5_hash = hashlib.md5()
    md5_hash.update(file_content)
    return md5_hash.hexdigest()


async def save_firmware_file(file: UploadFile, version: str) -> dict:
    """
    Save uploaded firmware file to local storage

    Args:
        file: Uploaded file from FastAPI
        version: Firmware version string

    Returns:
        dict with file_path, file_size, checksum, filename
    """
    # Create safe filename: version_originalname
    safe_filename = f"{version}_{file.filename}"
    file_path = os.path.join(FIRMWARE_DIR, safe_filename)

    # Read file content
    file_content = await file.read()

    # Write to disk
    with open(file_path, "wb") as f:
        f.write(file_content)

    # Calculate checksum and size
    file_size = len(file_content)
    checksum = calculate_checksum_from_bytes(file_content)

    return {
        "file_path": file_path,
        "filename": safe_filename,
        "file_size": file_size,
        "checksum": checksum
    }


def delete_firmware_file(file_path: str) -> bool:
    """
    Delete firmware file from filesystem

    Args:
        file_path: Path to the file

    Returns:
        True if deleted, False if file doesn't exist
    """
    if os.path.exists(file_path):
        os.remove(file_path)
        return True
    return False


def get_firmware_download_url(filename: str, base_url: str) -> str:
    """
    Generate download URL for firmware file

    Args:
        filename: Name of the firmware file
        base_url: Base URL of the server (e.g., https://your-server.com)

    Returns:
        Public download URL
    """
    # Remove trailing slash from base_url if present
    base_url = base_url.rstrip('/')
    return f"{base_url}/firmware/{filename}"


def get_file_size(file_path: str) -> int:
    """
    Get size of file in bytes

    Args:
        file_path: Path to the file

    Returns:
        File size in bytes
    """
    return os.path.getsize(file_path)


def file_exists(file_path: str) -> bool:
    """
    Check if file exists

    Args:
        file_path: Path to the file

    Returns:
        True if exists, False otherwise
    """
    return os.path.exists(file_path)
