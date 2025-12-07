from enum import Enum
import os
from typing import Protocol, runtime_checkable


class SemanticPathType(Enum):
    FILE = ""
    DIRECTORY = os.path.sep


def identify_semantic_path_type(path: str) -> SemanticPathType:
    if path in (".", ".."):
        return SemanticPathType.DIRECTORY

    if path.endswith(os.path.sep):
        return SemanticPathType.DIRECTORY

    if os.path.sep != "/" and path.endswith("/"):
        return SemanticPathType.DIRECTORY

    return SemanticPathType.FILE


@runtime_checkable
class SemanticPathLike(Protocol):
    def __fspath__(self) -> str: ...

    def __semantic_path_type__(self) -> SemanticPathType: ...
