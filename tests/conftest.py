from collections.abc import Iterator
import os
import pathlib

import pytest

import fluidpath
from fluidpath.semantic_pathtype import SemanticPathType


@pytest.fixture(scope="function")
def mock_fs(tmp_path: pathlib.Path) -> Iterator[fluidpath.Path]:
    root = tmp_path / "root"
    root.mkdir()

    (root / "a").mkdir()
    (root / "a" / "b").mkdir()
    (root / "a" / "b" / "file.txt").write_text("contents of b/file.txt")

    (root / "a" / "c").mkdir()
    (root / "a" / "c" / "file.txt").write_text("contents of c/file.txt")
    (root / "a" / "c" / "file2.log").write_text("contents of c/file2.log")
    (root / "a" / "c" / "d").mkdir()
    (root / "a" / "c" / "d" / "image.png").touch()

    (root / ".hidden-dir").mkdir()
    (root / ".hidden-dir" / "file.txt").write_text("contents of .hidden-dir/file.txt")
    (root / ".hidden-file").write_text("contents of .hidden-file")

    (root / "file.ext1.ext2.ext3").touch()
    (root / "no-extension").touch()
    (root / "trailing-dot.").touch()
    (root / "final-trailing-dot.ext.").touch()

    os.symlink(root / "a" / "b" / "file.txt", root / "symlink-to-file")
    os.symlink(root / "a", root / "symlink-to-dir")
    os.symlink(root / "nonexistent-target", root / "broken-symlink")

    yield fluidpath.Path._from_pathlib_path(root, semantic_path_type=SemanticPathType.DIRECTORY)
