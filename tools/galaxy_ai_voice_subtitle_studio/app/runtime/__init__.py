"""Shared runtime capability, model, resource, and job orchestration."""

from .jobs import TaskRecord, TaskRegistry

__all__ = ["TaskRecord", "TaskRegistry"]
