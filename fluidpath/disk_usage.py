from typing import NamedTuple


class DiskUsage(NamedTuple):
    """A named tuple representing disk usage statistics."""

    total: int
    used: int
    free: int
