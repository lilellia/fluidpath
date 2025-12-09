from enum import Enum
import os
from typing import Protocol, runtime_checkable


class SemanticPathType(Enum):
    """An enumeration of semantic path types."""

    FILE = ""
    DIRECTORY = os.path.sep


def identify_semantic_path_type(path: str) -> SemanticPathType:
    """Interpret the semantic meaning of the given string path.

    :param path: The path string to interpret.
    :returns: The interpreted semantic path type.
    """
    if path in (".", ".."):
        return SemanticPathType.DIRECTORY

    if path.endswith(os.path.sep):
        return SemanticPathType.DIRECTORY

    if os.path.sep != "/" and path.endswith("/"):
        return SemanticPathType.DIRECTORY

    return SemanticPathType.FILE


@runtime_checkable
class SemanticPathLike(Protocol):
    """A protocol class for semantic paths."""

    def __fspath__(self) -> str: ...

    def __semantic_path_type__(self) -> SemanticPathType: ...
