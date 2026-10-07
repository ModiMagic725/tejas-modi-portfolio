import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
CLIENT_EXTS = set(getattr(settings, "CLIENT_UPLOAD_EXTENSIONS", ["pdf", "doc", "docx", "png", "jpg", "jpeg", "zip"]))
CLIENT_MAX_MB = getattr(settings, "CLIENT_UPLOAD_MAX_MB", 10)
CLIENT_MAX_FILES = getattr(settings, "CLIENT_UPLOAD_MAX_FILES", 5)
PDF_MAX_MB = getattr(settings, "PDF_UPLOAD_MAX_MB", 20)
IMAGE_MAX_MB = getattr(settings, "IMAGE_UPLOAD_MAX_MB", 5)

# First bytes a genuine file of this type starts with (a cheap check against renamed files).
SIGNATURES = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
    "zip": (b"PK\x03\x04", b"PK\x05\x06"),
    "docx": (b"PK\x03\x04",),
    "doc": (b"\xd0\xcf\x11\xe0",),
}


def _ext(f):
    return os.path.splitext(f.name)[1].lower().lstrip(".")


def _check(f, allowed, max_mb):
    ext = _ext(f)
    if ext not in allowed:
        raise ValidationError(f"{f.name}: this file type is not supported.", code="type")
    if f.size > max_mb * 1024 * 1024:
        raise ValidationError(f"{f.name}: larger than {max_mb} MB.", code="size")
    if getattr(f, "_committed", False):  # already stored, nothing new to inspect
        return
    head = f.read(8)
    f.seek(0)
    if not any(head.startswith(s) for s in SIGNATURES.get(ext, ())):
        raise ValidationError(f"{f.name}: the file content does not match its type.", code="content")


def validate_client_file(f):
    _check(f, CLIENT_EXTS, CLIENT_MAX_MB)


def validate_pdf(f):
    _check(f, {"pdf"}, PDF_MAX_MB)


def validate_image(f):
    _check(f, IMAGE_EXTS, IMAGE_MAX_MB)


def validate_github_url(value):
    p = urlparse(value)
    if p.scheme != "https" or p.netloc.lower() not in ("github.com", "www.github.com"):
        raise ValidationError("Enter a GitHub link that starts with https://github.com/")