import os
import pathlib
from typing import cast

import pytest

from fluidpath import Path
from fluidpath.semantic_pathtype import identify_semantic_path_type, SemanticPathType


def force_windows_pure_path(path: str) -> Path:
    """Forcibly construct a Path using a PureWindowsPath. Only use for testing *pure* methods."""
    p = cast(pathlib.Path, pathlib.PureWindowsPath(path))
    return Path._from_pathlib_path(p, semantic_path_type=identify_semantic_path_type(path))


def force_posix_pure_path(path: str) -> Path:
    """Forcibly construct a Path using a PurePosixPath. Only use for testing *pure* methods."""
    p = cast(pathlib.Path, pathlib.PurePosixPath(path))
    return Path._from_pathlib_path(p, semantic_path_type=identify_semantic_path_type(path))


def test_from_pathlib_path_bypass() -> None:
    p = pathlib.Path("foo")
    assert Path._from_pathlib_path(p, semantic_path_type=SemanticPathType.FILE)._path is p


def test_home() -> None:
    assert isinstance(Path.home()._path, pathlib.Path)
    assert Path.home()._path == pathlib.Path.home()


def test_expand_user() -> None:
    p = Path("foo")
    assert isinstance(p.expand_user()._path, pathlib.Path)
    assert p.expand_user()._path == pathlib.Path("foo").expanduser()


def test_from_uri_valid() -> None:
    uri = "file:///foo"
    assert isinstance(Path.from_uri(uri)._path, pathlib.Path)
    assert Path.from_uri(uri)._path == pathlib.Path("/foo")


def test_from_uri_invalid() -> None:
    with pytest.raises(ValueError, match="invalid file URI: foo"):
        Path.from_uri("foo")


@pytest.mark.parametrize(
    "path, uri",
    [
        (Path("/foo"), "file:///foo"),
        (Path("/foo/bar"), "file:///foo/bar"),
        (Path("/foo/bar/baz"), "file:///foo/bar/baz"),
    ],
)
def test_as_uri_valid(path: Path, uri: str) -> None:
    assert path.as_uri() == uri


def test_as_uri_invalid() -> None:
    with pytest.raises(ValueError, match="relative path can't be expressed as a file URI"):
        Path("foo").as_uri()


def test_truediv_valid() -> None:
    p = Path("foo") / "bar" / "baz"

    assert isinstance(p._path, pathlib.Path)
    assert p._path == pathlib.Path("foo/bar/baz")


def test_truediv_invalid() -> None:
    with pytest.raises(TypeError, match="unsupported operand type"):
        Path("foo") / 27  # type: ignore


def test_parts() -> None:
    p = Path("foo") / "bar" / "baz"
    assert p.parts == ("foo", "bar", "baz")


def test_components() -> None:
    p = Path("foo") / "bar" / "baz"
    assert p.components == ("foo", "bar", "baz")


@pytest.mark.parametrize(
    "path, drive",
    [
        (force_windows_pure_path("C:/foo/bar"), "C:"),
        (force_windows_pure_path("//host/share/foo/bar"), "\\\\host\\share"),
        (force_windows_pure_path("/foo/bar"), ""),
    ],
)
def test_drive_windows(path: Path, drive: str) -> None:
    assert path.drive == drive


@pytest.mark.parametrize(
    "path, drive",
    [
        (force_posix_pure_path("C:/foo/bar"), ""),
        (force_posix_pure_path("//host/share/foo/bar"), ""),
        (force_posix_pure_path("/foo/bar"), ""),
    ],
)
def test_drive_posix(path: Path, drive: str) -> None:
    assert path.drive == drive


@pytest.mark.parametrize(
    "path, root",
    [
        (force_windows_pure_path("C:/Program Files/"), "\\"),
        (force_windows_pure_path("C:Program Files/"), ""),
        (force_windows_pure_path("//host/share/foo/bar"), "\\"),
        (force_windows_pure_path("/foo/bar"), "\\"),
    ],
)
def test_root_windows(path: Path, root: str) -> None:
    assert path.root == root


@pytest.mark.parametrize(
    "path, root",
    [
        (force_posix_pure_path("//etc"), "//"),
        (force_posix_pure_path("///etc"), "/"),
        (force_posix_pure_path("/////etc"), "/"),
    ],
)
def test_root_posix(path: Path, root: str) -> None:
    assert path.root == root


@pytest.mark.parametrize(
    "path, anchor",
    [
        (force_windows_pure_path("C:/Program Files/"), "C:\\"),
        (force_windows_pure_path("C:Program Files/"), "C:"),
        (force_windows_pure_path("//host/share/foo/bar"), "\\\\host\\share\\"),
        (force_posix_pure_path("/etc"), "/"),
    ],
)
def test_anchor(path: Path, anchor: str) -> None:
    assert path.anchor == anchor


def test_parents() -> None:
    p = Path("foo") / "bar" / "baz"
    assert p.parents == (Path("foo/bar/"), Path("foo/"), Path("."))


def test_parent() -> None:
    p = Path("foo") / "bar" / "baz"
    assert p.parent == Path("foo/bar/")


def test_name() -> None:
    p = Path("foo") / "bar" / "baz.txt"
    assert p.name == "baz.txt"


@pytest.mark.parametrize(
    "path, suffix",
    [
        (Path("/path/to/foo"), ""),
        (Path("/path/to/foo.txt"), ".txt"),
        (Path("/path/to/foo/bar.jpg"), ".jpg"),
        (Path("/path/to/foo/bar/baz.tar.gz"), ".gz"),
        (Path("."), ""),
        (Path("./foo"), ""),
    ],
)
def test_suffix(path: Path, suffix: str) -> None:
    assert path.suffix == suffix


@pytest.mark.parametrize(
    "path, suffix",
    [
        (Path("/path/to/foo."), "."),
        (Path("/path/to/foo.txt."), "."),
        (Path("/path/to/foo.txt..........."), "."),
        (Path("/path/to/foo.txt.jpg.tar.gz.docx."), "."),
        (Path("./foo."), "."),
        (Path("." * 1), ""),
        (Path("." * 2), ""),
        (Path("." * 3), ""),
        (Path("." * 37), ""),
        (Path("." * 12_142_896), ""),
    ],
)
def test_suffix_trailing_dot(path: Path, suffix: str) -> None:
    assert path.suffix == suffix


@pytest.mark.parametrize(
    "path, suffixes",
    [
        (Path("/path/to/foo"), []),
        (Path("/path/to/foo.txt"), [".txt"]),
        (Path("/path/to/foo/bar.jpg"), [".jpg"]),
        (Path("/path/to/foo/bar/baz.tar.gz"), [".tar", ".gz"]),
        (Path("./foo"), []),
    ],
)
def test_suffixes(path: Path, suffixes: list[str]) -> None:
    assert path.suffixes == suffixes


@pytest.mark.parametrize(
    "path, suffixes",
    [
        (Path("/path/to/foo."), ["."]),
        (Path("/path/to/foo.txt."), [".txt", "."]),
        (Path("/path/to/foo.txt..........."), [".txt", "."]),
        (Path("/path/to/foo.txt.jpg.tar.gz.docx."), [".txt", ".jpg", ".tar", ".gz", ".docx", "."]),
        (Path("./foo."), ["."]),
        (Path("." * 1), []),
        (Path("." * 2), []),
        (Path("." * 3), []),
        (Path("." * 37), []),
        (Path("." * 12_142_896), []),
    ],
)
def test_suffixes_trailing_dot(path: Path, suffixes: list[str]) -> None:
    assert path.suffixes == suffixes


def test_stem() -> None:
    p = Path("foo") / "bar" / "baz.txt"
    assert p.stem == "baz"


def test_absolute(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = Path("a") / "c" / "file.txt"
    assert p.absolute() == mock_fs / "a" / "c" / "file.txt"


def test_is_absolute_true(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "c" / "file.txt"
    assert p.is_absolute()


def test_is_absolute_false(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = Path("a") / "c" / "file.txt"
    assert not p.is_absolute()


def test_resolve_regular_file(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = Path("a") / "c" / "file.txt"
    assert p.resolve() == mock_fs / "a" / "c" / "file.txt"


def test_resolve_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-file --> mock_fs/a/b/file.txt
    p = Path("symlink-to-file")
    assert p.resolve() == mock_fs / "a" / "b" / "file.txt"


def test_read_link_with_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-file --> mock_fs/a/b/file.txt
    p = Path("symlink-to-file")
    assert p.read_link() == mock_fs / "a" / "b" / "file.txt"


def test_read_link_with_symlink_to_dir(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-dir --> mock_fs/a
    p = Path("symlink-to-dir")
    assert p.read_link() == mock_fs / "a/"


def test_read_link_with_broken_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/broken-symlink --> nonexistent-target
    p = Path("broken-symlink")
    assert p.read_link() == mock_fs / "nonexistent-target"


def test_read_link_with_non_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    with pytest.raises(OSError, match="Invalid argument"):
        p.read_link()


def test_stat_regular_file(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    assert p.stat() == os.stat(p)


def test_stat_symlink(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-file --> mock_fs/a/b/file.txt
    p = Path("symlink-to-file")
    assert p.stat() == os.stat(p)
    assert p.stat() == os.stat(p.read_link())


def test_stat_symlink_follow_false(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-file --> mock_fs/a/b/file.txt
    p = Path("symlink-to-file")
    assert p.stat(follow_symlinks=False) == os.lstat(p)
    assert p.stat(follow_symlinks=False) != os.stat(p.read_link())


def test_stat_symlink_to_dir(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    # NB: mock_fs/symlink-to-dir --> mock_fs/a
    p = Path("symlink-to-dir")
    assert p.stat() == os.stat(p)
    assert p.stat() == os.stat(p.read_link())


def test_is_relative_to_true_with_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert p.is_relative_to(q, strict=True)


def test_is_relative_to_true_without_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert p.is_relative_to(q)


def test_is_relative_to_false_with_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert not q.is_relative_to(p, strict=True)


def test_is_relative_to_false_without_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert not q.is_relative_to(p)


def test_is_relative_to_literal_true_semantic_false_without_strict(
    mock_fs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    q = mock_fs / "a" / "b" / ".."  # mock_fs/a

    assert q.is_relative_to(p, strict=False)


def test_is_relative_to_literal_true_semantic_false_with_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    q = mock_fs / "a" / "b" / ".."  # mock_fs/a

    assert not q.is_relative_to(p, strict=True)


def test_relative_to_true_with_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert p.relative_to(q, strict=True) == Path("b/file.txt")


def test_relative_to_true_without_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    q = mock_fs / "a"
    assert p.relative_to(q) == Path("b/file.txt")


def test_relative_to_literal_true_semantic_false_without_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    q = mock_fs / "a" / "b" / ".."  # mock_fs/a

    assert q.relative_to(p, strict=False) == Path("..")


def test_relative_to_literal_true_semantic_false_with_strict(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b"
    q = mock_fs / "a" / "b" / ".."  # mock_fs/a

    with pytest.raises(ValueError):
        q.relative_to(p, strict=True)


def test_is_reserved_windows_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "isreserved", lambda _: True, raising=False)

    p = force_windows_pure_path("C://User/CON")
    assert p.is_reserved()


def test_is_reserved_windows_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "isreserved", lambda _: False, raising=False)

    p = force_windows_pure_path("C://User/Documents/File.txt")
    assert not p.is_reserved()


def test_is_reserved_posix_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "isreserved", lambda _: False, raising=False)

    p = force_posix_pure_path("/var/log/file.log")
    assert not p.is_reserved()


def test_join_path_zero_layers() -> None:
    p = Path("root") / "a" / "b"
    assert p.join_path() == Path("root") / "a" / "b"


def test_join_path_one_layer() -> None:
    p = Path("root") / "a" / "b"
    assert p.join_path("file.txt") == Path("root") / "a" / "b" / "file.txt"


def test_join_path_two_layer() -> None:
    p = Path("root") / "a"
    assert p.join_path("b", "file.txt") == Path("root") / "a" / "b" / "file.txt"


def test_with_name_valid() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.with_name("new-name.txt") == Path("root") / "a" / "b" / "new-name.txt"


def test_with_name_to_empty_name() -> None:
    p = Path("root") / "a" / "b" / "file.txt"

    with pytest.raises(ValueError, match="Invalid name ''"):
        p.with_name("")


def test_with_name_with_empty_name() -> None:
    p = Path("")
    with pytest.raises(ValueError, match="has an empty name"):
        p.with_name("new-name.txt")


def test_with_stem_valid() -> None:
    p = Path("root") / "a" / "b" / "file.txt"
    assert p.with_stem("new-name") == Path("root") / "a" / "b" / "new-name.txt"


def test_with_stem_to_empty_name() -> None:
    p = Path("root") / "a" / "b" / "file.txt"

    with pytest.raises(ValueError, match="has a non-empty suffix"):
        p.with_stem("")


def test_with_stem_with_empty_name() -> None:
    p = Path("")
    with pytest.raises(ValueError, match="has an empty name"):
        p.with_stem("new-name")


def test_with_suffix_normal() -> None:
    p = Path("root") / "a" / "b.txt"
    assert p.with_suffix(".new") == Path("root") / "a" / "b.new"


def test_with_suffix_remove() -> None:
    p = Path("root") / "a" / "b.txt"
    assert p.with_suffix("") == Path("root") / "a" / "b"


def test_with_suffix_remove_with_multiple() -> None:
    p = Path("root") / "a" / "b.txt.ext"
    assert p.with_suffix("") == Path("root") / "a" / "b.txt"


def test_with_suffix_with_empty_name() -> None:
    p = Path("")
    with pytest.raises(ValueError, match="has an empty name"):
        p.with_suffix(".new")


def test_with_suffix_with_trailing_dot() -> None:
    p = Path("root") / "a" / "b.txt"
    assert p.with_suffix(".new.") == Path("root") / "a" / "b.new."


def test_exists_true(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "file.txt"
    assert p.exists()


def test_exists_false(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "a" / "b" / "does-not-exist"
    assert not p.exists()


def test_exists_symlink_valid(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "symlink-to-file"
    assert p.exists()


def test_exists_symlink_broken_following(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "broken-symlink"
    assert not p.exists(follow_symlinks=True)


def test_exists_symlink_broken_not_following(mock_fs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(mock_fs)

    p = mock_fs / "broken-symlink"
    assert p.exists(follow_symlinks=False)
