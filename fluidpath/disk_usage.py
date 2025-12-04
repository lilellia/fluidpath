from typing import NamedTuple


class DiskUsage(NamedTuple):
    total: int
    used: int
    free: int
