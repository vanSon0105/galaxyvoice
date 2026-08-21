"""Shared exception types for task cancellation across services."""


class TaskCancelledError(RuntimeError):
    """Raised by services when a stop_event is set mid-task.

    The web task wrapper maps this to a 'cancelled' terminal status; the
    UI layers treat it like any other RuntimeError.
    """

    def __init__(self, message: str = "Task was cancelled.") -> None:
        super().__init__(message)
