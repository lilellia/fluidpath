from enum import auto, Enum
import stat


class PathType(Enum):
    """An enumeration of various physical path types."""
    REGULAR_FILE = auto()
    DIRECTORY = auto()
    SYMLINK = auto()
    PIPE = auto()
    CHAR_DEVICE = auto()
    BLOCK_DEVICE = auto()
    SOCKET = auto()
    UNKNOWN = auto()
    DOES_NOT_EXIST = auto()


def identify_st_mode(mode: int) -> PathType:
    """Identify the path type from the given stat mode.
    
    :param mode: The mode of the path, as returned by :py:func:`os.stat`, via `os.stat(path).st_mode`.
    :returns: The path type
    """
    if stat.S_ISREG(mode):
        return PathType.REGULAR_FILE

    if stat.S_ISDIR(mode):
        return PathType.DIRECTORY

    if stat.S_ISLNK(mode):
        return PathType.SYMLINK

    if stat.S_ISFIFO(mode):
        return PathType.PIPE

    if stat.S_ISCHR(mode):
        return PathType.CHAR_DEVICE

    if stat.S_ISBLK(mode):
        return PathType.BLOCK_DEVICE

    if stat.S_ISSOCK(mode):
        return PathType.SOCKET

    return PathType.UNKNOWN
