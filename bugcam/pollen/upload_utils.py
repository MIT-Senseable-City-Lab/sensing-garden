"""Shared helper producers lean on when staging an artifact for upload: the
content type for a filename. Pollen itself uses this (transport.py); produce-side
decisions like whether a result dir has anything worth shipping live with the
producer (bugcam.edge26.result_publish), not here.
"""
from __future__ import annotations

JSON = "application/json"


def content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".mp4"):
        return "video/mp4"
    if lowered.endswith(".json"):
        return JSON
    if lowered.endswith((".log", ".txt")):
        return "text/plain"
    if lowered.endswith(".tar"):
        return "application/x-tar"
    return "application/octet-stream"
