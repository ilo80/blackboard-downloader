"""User-facing failures that never expose credentials or signed URL queries."""


class BlackboardError(Exception):
    """An expected connection, content, or export failure."""


class AuthenticationError(BlackboardError):
    """Authentication failed or the session expired."""


class ApiError(BlackboardError):
    """A Blackboard request failed with an HTTP status."""

    def __init__(self, status: int, path: str):
        self.status = status
        super().__init__(f"HTTP {status}: {path}")
