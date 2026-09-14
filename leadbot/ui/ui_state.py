"""Shared state for the local LeadBot web console."""

from threading import Lock

JOB = {"status": "idle", "progress": 0, "message": "Ready", "log": []}
JOB_LOCK = Lock()
RUN_TIMEOUT_SECONDS = 1800
