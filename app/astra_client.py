import os
import requests

ASTRA_TOKEN = os.getenv("ASTRA_ACCESS_TOKEN")
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SEC", "120"))

def _headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0"
    }

def upload_video(upload_url: str, video_path: str, token: str):
    with open(video_path, "rb") as f:
        r = requests.post(
            upload_url,
            headers=_headers(token),
            files={"file": f},
            timeout=TIMEOUT
        )
    if r.status_code in (401, 403):
        raise RuntimeError("TOKEN_EXPIRED")
    r.raise_for_status()
    return r.json()  # {fileId/uploadId}

def create_job(process_url: str, payload: dict, token: str):
    r = requests.post(
        process_url,
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=TIMEOUT
    )
    if r.status_code in (401, 403):
        raise RuntimeError("TOKEN_EXPIRED")
    r.raise_for_status()
    return r.json()  # {jobId}

def get_status(status_url: str, token: str):
    r = requests.get(status_url, headers=_headers(token), timeout=TIMEOUT)
    if r.status_code in (401, 403):
        raise RuntimeError("TOKEN_EXPIRED")
    r.raise_for_status()
    return r.json()

def download_result(download_url: str, token: str):
    r = requests.get(download_url, headers=_headers(token), timeout=TIMEOUT, stream=True)
    if r.status_code in (401, 403):
        raise RuntimeError("TOKEN_EXPIRED")
    r.raise_for_status()
    return r
