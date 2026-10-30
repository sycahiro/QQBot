"""Only this launch's bounded log tail; stable byte-offset identities precede redaction."""

import os
import re


def read_log_entries(paths, secrets=()):
    file = paths.logs / "desktop.log"
    if not file.exists():
        return []
    with file.open("rb") as stream:
        identity = os.fstat(stream.fileno())
        start = max(0, identity.st_size - 65536)
        stream.seek(start)
        raw = stream.read(65536)
    if start:
        # Never display a partial first line, including partial credentials.
        boundary = raw.find(b"\n")
        if boundary < 0:
            return []
        start += boundary + 1
        raw = raw[boundary + 1 :]
    entries = []
    keys = sorted({secret for secret in secrets if secret}, key=len, reverse=True)
    for line in raw.splitlines(keepends=True):
        text = line.rstrip(b"\r\n").decode("utf-8", errors="replace")
        for secret in keys:
            text = text.replace(secret, "[密钥已隐藏]")
        text = re.sub(r"(?i)\bBearer\s+[^\s\"']+", "Bearer [已隐藏]", text)
        entries.append({"id": f"{identity.st_dev}:{identity.st_ino}:{start}", "text": text[:2000]})
        start += len(line)
    return entries[-200:]


def read_logs(paths, secrets=()):
    return [entry["text"] for entry in read_log_entries(paths, secrets)]
