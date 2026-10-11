"""Download HTTP resources atomically, with optional validation before publication.

Copyright (C) 2026
"""

import os
import tempfile
from collections.abc import Callable

import requests


def download_file(url: str, destination: str, *, validate: Callable[[str], None] | None = None, timeout: float = 60) -> None:
    """Download to a temporary file, validate it, and atomically replace destination.

    HTTP failures, incomplete transfers, and validation failures propagate. The
    destination is preserved when downloading or validation fails.

    Parameters
    ----------
    url : str
        HTTP resource URL.
    destination : str
        Local destination path.
    validate : callable or None, default=None
        Optional callback that validates the downloaded temporary file path.
    timeout : float, default=60
        Request timeout in seconds.

    Raises
    ------
    OSError
        If the transfer is incomplete or filesystem operations fail.
    """
    folder = os.path.dirname(os.path.abspath(destination))
    os.makedirs(folder, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as stream, requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            size = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                stream.write(chunk)
                size += len(chunk)
            length = response.headers.get("Content-Length")
            if length is not None and not response.headers.get("Content-Encoding") and size != int(length):
                raise OSError(f"Incomplete download from {url}: expected {length} bytes, received {size}.")
        if validate is not None:
            validate(temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
