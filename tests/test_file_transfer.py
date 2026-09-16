"""
Tests for FileTransferManager in NebulaLab OS
"""
import os
import tempfile
import pytest
from file_transfer import FileTransferManager

@pytest.fixture
def temp_storage():
    temp_dir = tempfile.TemporaryDirectory()
    ftm = FileTransferManager(storage_dir=temp_dir.name)
    yield ftm, temp_dir.name
    temp_dir.cleanup()

@pytest.mark.asyncio
async def test_file_upload_and_integrity(temp_storage):
    ftm, storage_dir = temp_storage
    content = b"Hello NebulaLab Distributed Cloud!"
    filename = "test_script.sh"

    res = await ftm.save_uploaded_file(filename, content, encrypt=False)
    assert res["filename"] == "test_script.sh"
    assert res["size_bytes"] == len(content)
    assert res["checksum"] != ""

    # Verify file content
    fetched = await ftm.get_file_content(filename, decrypt=False)
    assert fetched == content

@pytest.mark.asyncio
async def test_file_encryption_and_decryption(temp_storage):
    ftm, storage_dir = temp_storage
    content = b"Secret cluster configuration token 12345"
    filename = "secret.env"

    res = await ftm.save_uploaded_file(filename, content, encrypt=True)
    assert res["encrypted"] is True

    # Raw file on disk should NOT match plaintext
    raw_disk = await ftm.get_file_content(filename, decrypt=False)
    assert raw_disk != content

    # Decrypted content should match original
    decrypted = await ftm.get_file_content(filename, decrypt=True)
    assert decrypted == content

@pytest.mark.asyncio
async def test_path_traversal_guard(temp_storage):
    ftm, storage_dir = temp_storage
    # Attempting to read outside storage directory
    bad_path = "../../etc/passwd"
    safe_path = ftm._get_safe_path(bad_path)
    # _get_safe_path strips directories and uses basename
    assert os.path.dirname(safe_path) == os.path.abspath(storage_dir)

@pytest.mark.asyncio
async def test_file_deletion(temp_storage):
    ftm, storage_dir = temp_storage
    content = b"temporary log file"
    filename = "temp.log"

    await ftm.save_uploaded_file(filename, content)
    files_before = ftm.list_shared_files()
    assert len(files_before) == 1

    # Delete
    deleted = await ftm.delete_file(filename)
    assert deleted is True

    files_after = ftm.list_shared_files()
    assert len(files_after) == 0

    # Delete non-existent
    deleted_nonexistent = await ftm.delete_file("nonexistent.txt")
    assert deleted_nonexistent is False
