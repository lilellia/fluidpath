from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
import fnmatch
import os
import os.path
import pathlib
import re
import shutil
import sys
import tempfile
from typing import Any, BinaryIO, cast, IO, Literal, overload, TextIO, TypeVar

if sys.version_info >= (3, 11):
    from collections.abc import Buffer
    from typing import Self
else:
    from typing_extensions import Buffer, Self

from .disk_usage import DiskUsage
from .pathtype import identify_st_mode, PathType
from .semantic_pathtype import identify_semantic_path_type, SemanticPathLike, SemanticPathType
from .size_unit_prefixes import BinarySizePrefix, DecimalSizePrefix, SIZE_PREFIX_CONVERSIONS

_P = TypeVar("_P", bound="Path")


class Path:
    def __init__(self, *segments: str | os.PathLike[str]) -> None:
        semantics = SemanticPathType.DIRECTORY

        if segments:
            tail = segments[-1]
            if isinstance(tail, SemanticPathLike):
                semantics = self._identify_semantic_path_type(tail)
            elif isinstance(tail, str):
                semantics = identify_semantic_path_type(tail)
            else:
                raise TypeError(
                    "tail element of path must be a str or implement __semantic_path_type__(). "
                    f"Semantically ambiguous {type(tail)} is invalid."
                )

        self._path = pathlib.Path(*segments)
        self._semantic_path_type = semantics

    def __fspath__(self) -> str:
        return self._path.__fspath__()

    def __semantic_path_type__(self) -> SemanticPathType:
        return self._semantic_path_type

    def __str__(self) -> str:
        return os.path.normpath(str(self._path)) + self._semantic_path_type.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._path}{self._semantic_path_type.value})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, type(self)):
            return str(self) == str(other)

        if isinstance(other, pathlib.Path):
            return self._path == other

        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._path)

    @classmethod
    def _identify_semantic_path_type(cls, path: str | SemanticPathLike) -> SemanticPathType:
        if isinstance(path, SemanticPathLike):
            return path.__semantic_path_type__()

        if isinstance(path, str):
            return identify_semantic_path_type(path)

        raise TypeError(f"expected str or SemanticPathLike, not {type(path)}")

    @classmethod
    def _from_pathlib_path(cls, path: pathlib.Path, *, semantic_path_type: SemanticPathType) -> Self:
        """Return an instance of this class from a pathlib.Path instance, avoiding the initialization overhead."""
        inst = cls.__new__(cls)
        inst._path = path
        inst._semantic_path_type = semantic_path_type
        return inst

    @classmethod
    def home(cls) -> Self:
        """Return a new path object for the user's home directory."""
        return cls._from_pathlib_path(pathlib.Path.home(), semantic_path_type=SemanticPathType.DIRECTORY)

    def expand_user(self) -> Self:
        """Return a new path object with the user's home directory expanded."""
        return type(self)._from_pathlib_path(self._path.expanduser(), semantic_path_type=self._semantic_path_type)

    @classmethod
    def cwd(cls) -> Self:
        """Return a new path object for the current working directory."""
        return cls._from_pathlib_path(pathlib.Path.cwd(), semantic_path_type=SemanticPathType.DIRECTORY)

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Return a new path object from parsing a file URI.
        ValueError is raised if the URI is invalid or the path is not absolute.
        """
        if not (match := re.match(r"file://(.*)", uri)):
            raise ValueError(f"invalid file URI: {uri}")

        filepath = match.group(1)
        semantic_path_type = cls._identify_semantic_path_type(filepath)
        return cls._from_pathlib_path(pathlib.Path(filepath), semantic_path_type=semantic_path_type)

    def as_uri(self) -> str:
        """Return a string representing the path as a file URI.
        ValueError is raised if the path is not absolute.
        """
        return self._path.as_uri() + self._semantic_path_type.value

    @classmethod
    @contextmanager
    def temporary_file(
        cls,
        *,
        suffix: str | None = None,
        prefix: str | None = None,
        parent: str | os.PathLike[str] | None = None,
        delete: bool = True,
    ) -> Iterator[Self]:
        """Return a path pointing to a temporary file.

        This object can be used within a context manager (`with Path.temporary_file() as p: ...`).
        Unless `delete=False`, the temporary file is automatically deleted when the context manager exits.
        """
        # We immediately close the file handler because we don't want to impede on further reads/writes
        # while our context manager is active.
        f, abspath = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=parent)
        os.close(f)

        p = cls(abspath)

        try:
            yield p
        finally:
            if delete:
                p.delete(force=True)

    @classmethod
    @contextmanager
    def temporary_directory(
        cls,
        *,
        suffix: str | None = None,
        prefix: str | None = None,
        parent: str | os.PathLike[str] | None = None,
        delete: bool = True,
    ) -> Iterator[Self]:
        """Return a path pointing to a temporary directory.

        This object can be used within a context manager (`with Path.temporary_directory() as p: ...`).
        Unless `delete=False`, the temporary directory is automatically deleted when the context manager exits.
        """
        temp_dir = cls(tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=parent) + os.path.sep)

        try:
            yield temp_dir
        finally:
            if delete:
                temp_dir.delete(force=True)

    def __truediv__(self, other: str | SemanticPathLike) -> Self:
        """Return a new path by joining the given path with this path."""
        if not isinstance(other, (str, SemanticPathLike)):
            return NotImplemented

        semantic_path_type = self._identify_semantic_path_type(other)
        return type(self)._from_pathlib_path(self._path / other, semantic_path_type=semantic_path_type)

    @property
    def parts(self) -> tuple[str, ...]:
        """Return a tuple of the path's components."""
        parts = list(self._path.parts)
        if parts and parts[-1] != os.path.sep:
            parts[-1] = f"{parts[-1]}{self._semantic_path_type.value}"

        return tuple(parts)

    @property
    def components(self) -> tuple[str, ...]:
        """Return a tuple of the path's components. This is an alias for Path.parts."""
        return self.parts

    @property
    def drive(self) -> str:
        """Return a string representing the drive (e.g., "C:" on Windows).

        UNC shares are also considered drives:

        >>> Path('//host/share/foo.txt').drive
        '\\\\host\\share'
        """
        return self._path.drive

    @property
    def root(self) -> str:
        """Return a string representing the path's root (if any).

        UNC shares always have a root:
        >>> Path('//host/share/foo.txt').root
        '\\'
        """
        return self._path.root

    @property
    def anchor(self) -> str:
        """The concaentation of the drive and root."""
        return self._path.anchor

    def _get_parents_impl(self: _P) -> tuple[_P, ...]:
        """Return a tuple of the path's parent directories.
        This is an internal method provided as an implementation detail for the parents property
        in order to work around known mypy limitations. Hence the unusual typing of `self: _P.`
        """
        return tuple(
            type(self)._from_pathlib_path(p, semantic_path_type=SemanticPathType.DIRECTORY) for p in self._path.parents
        )

    @property
    def parents(self) -> tuple[Self, ...]:
        """Return a tuple of the path's parent directories."""
        return self._get_parents_impl()

    @property
    def parent(self) -> Self:
        """Return the path's parent directory."""
        return type(self)._from_pathlib_path(self._path.parent, semantic_path_type=SemanticPathType.DIRECTORY)

    @property
    def name(self) -> str:
        """Return a string representing the path's last component, excluding the drive and root."""
        return self._path.name

    @property
    def suffix(self) -> str:
        """Return a string representing the path's last component's suffix."""
        if re.fullmatch(r"\.+", str(self)):
            # special case: when the path is all dots ("...."), the suffix is always empty
            return ""

        if str(self).endswith("."):
            # when the path ends with a dot (but is not all dots), the suffix is "."
            return "."

        return self._path.suffix

    @property
    def suffixes(self) -> list[str]:
        """Return a list of strings representing the path's last component's suffixes."""
        if re.fullmatch(r"\.+", str(self)):
            # special case: when the path is all dots ("...."), the suffix is always empty
            return []

        if str(self).endswith("."):
            # when the path ends with a dot (but is not all dots), the trailing suffix is "."
            return self.with_name(self.name.rstrip(".")).suffixes + ["."]

        return self._path.suffixes

    @property
    def stem(self) -> str:
        """Return a string representing the path's last component, excluding the suffix."""
        return self._path.stem

    def absolute(self) -> Self:
        """Return a new path with the path made absolute, without normalizing or resolving symlinks."""
        return type(self)._from_pathlib_path(self._path.absolute(), semantic_path_type=self._semantic_path_type)

    def is_absolute(self) -> bool:
        """Return whether the path is absolute or not (i.e., includes a root and, as allowed, a drive)."""
        return self._path.is_absolute()

    def resolve(self, *, strict: bool = False) -> Self:
        """Return a new absolute path with all symlinks resolved."""
        try:
            # resolve the path using pathlib.Path, then determine the semantic path type by querying what was there
            resolved = self._path.resolve(strict=strict)
            semantic_pathtype = SemanticPathType.DIRECTORY if resolved.is_dir() else SemanticPathType.FILE
        except FileNotFoundError:
            # fall back, preserving the semantic path type of this path
            resolved = self._path.absolute()
            semantic_pathtype = self._semantic_path_type

        return type(self)._from_pathlib_path(resolved, semantic_path_type=semantic_pathtype)

    def conform_to_filesystem(self) -> Self:
        """Return a new path that semantically matches the path on the filesystem while normalizing the path.

        For example:
        >>> p = Path("/path/to/existing/file/")  # note the trailing slash
        >>> p._semantic_path_type
        SemanticPathType.DIRECTORY

        >>> p.conform_to_filesystem()     # note the lack of trailing slash
        Path(""/path/to/existing/file)
        >>> p.conform_to_filesystem()._semantic_path_type
        SemanticPathType.FILE
        """
        target = pathlib.Path(os.path.normpath(str(self)))

        try:
            # resolve the semantic type by checking the path on the filesystem
            semantic_pathtype = SemanticPathType.DIRECTORY if target.is_dir() else SemanticPathType.FILE
        except FileNotFoundError:
            # fall back to using the existing path semantics
            semantic_pathtype = self._semantic_path_type

        return type(self)._from_pathlib_path(target, semantic_path_type=semantic_pathtype)

    def read_link(self) -> Self:
        """Return a new path representing the target of a symbolic link."""
        target_str = os.readlink(str(self))
        target = pathlib.Path(target_str)

        try:
            # resolve the semantic type by checking the link target on the filesystem
            full_path = self._path.parent / target
            semantic_pathtype = SemanticPathType.DIRECTORY if full_path.is_dir() else SemanticPathType.FILE
        except FileNotFoundError:
            # fall back to using the string representation
            semantic_pathtype = identify_semantic_path_type(target_str)

        return type(self)._from_pathlib_path(target, semantic_path_type=semantic_pathtype)

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        """Return an os.stat_result object containing information about this path, like os.stat.
        The result is looked up at each call to this method.

        Use `follow_symlinks=False` to stat a symlink itself.
        """
        return self._path.stat(follow_symlinks=follow_symlinks)

    def is_relative_to(self, other: str | os.PathLike[str], *, strict: bool = False) -> bool:
        """Return whether the path is relative to another path.

        By default (strict=False), this method is string-based and does not access the filesystem nor
        treat ".." segments specially.

        If strict=True, the paths are resolved and handled appropriately.
        """
        if strict:
            target, root = self._path.resolve(), pathlib.Path(other).resolve()
        else:
            target, root = self._path, pathlib.Path(other)

        return target.is_relative_to(root)

    def relative_to(self, other: str | os.PathLike[str], *, strict: bool = False) -> Self:
        """Compute a version of this path relative to the path represented by `other`.

        By default (strict=False), this method is string-based and does not access the filesystem nor
        treat ".." segments specially.

        If strict=True, the paths are resolved and handled appropriately.
        """
        if strict:
            target, root = self._path.resolve(), pathlib.Path(other).resolve()
        else:
            target, root = self._path, pathlib.Path(other)

        return type(self)._from_pathlib_path(target.relative_to(root), semantic_path_type=self._semantic_path_type)

    def is_reserved(self) -> bool:
        """Return True if the path is reserved on the current platform. For non-Windows platforms, this is False."""
        if sys.version_info < (3, 13):
            return self._path.is_reserved()

        return os.path.isreserved(self)

    def join_path(self, *other: str | os.PathLike[str]) -> Self:
        """Return a new path by joining the given path with this path."""
        if not other:
            return self

        semantics = SemanticPathType.DIRECTORY
        tail = other[-1]

        if isinstance(tail, (SemanticPathLike, str)):
            semantics = self._identify_semantic_path_type(tail)
        else:
            raise TypeError(
                "tail element of path must be a str or implement __semantic_path_type__(). "
                f"Semantically ambiguous {type(tail)} is invalid."
            )

        return type(self)._from_pathlib_path(self._path.joinpath(*other), semantic_path_type=semantics)

    def match(self, pattern: str | re.Pattern[str], *, full: bool = True, case_sensitive: bool = True) -> bool:
        """Match this path against the provided regex pattern. Returns True if the path matches the pattern.

        If `full` is True, then the pattern is applied to the full path;
        if False, then the pattern need not match the entire path.

        WARNING:
        This function does not behave in the same way as pathlib.PurePath.match.
        For pathlib.PurePath.match functionality, use .glob_match.
        """
        match_func = re.fullmatch if full else re.search
        flags = re.IGNORECASE if not case_sensitive else 0
        return match_func(pattern, str(self), flags=flags) is not None

    def glob_match(self, glob: str, *, full: bool = True, case_sensitive: bool = True) -> bool:
        """Match this path against the provided glob pattern. Returns True if the path matches the pattern.

        If `full` is True, then the glob pattern is applied to the full path;
        if False, then the pattern need not match the entire path.
        """
        return self.match(fnmatch.translate(glob), full=full, case_sensitive=case_sensitive)

    def with_name(self, name: str) -> Self:
        """Return a path with the file name changed to `name`.
        If the original path doesn't have a name, ValueError is raised.
        """
        return type(self)._from_pathlib_path(self._path.with_name(name), semantic_path_type=self._semantic_path_type)

    def with_stem(self, stem: str) -> Self:
        """Return a path with the file stem changed to `stem`.
        If the original path doesn't have a name, ValueError is raised.
        """
        return type(self)._from_pathlib_path(self._path.with_stem(stem), semantic_path_type=self._semantic_path_type)

    def with_suffix(self, suffix: str) -> Self:
        """Return a path with the file suffix changed to `suffix`.
        If the original path doesn't have a suffix, then the suffix is appended instead.
        If the suffix is an empty string, the original suffix is removed.

        The suffix may be the string ".", in which case, it is used literally;
        before Python 3.14, pathlib.PurePath.with_suffix(self, ".") would raise a ValueError.
        """
        if suffix == ".":
            p = type(self)(f"{self._path.with_suffix('')}.")
            p._semantic_path_type = self._semantic_path_type
            return p

        return type(self)._from_pathlib_path(
            self._path.with_suffix(suffix), semantic_path_type=self._semantic_path_type
        )

    def exists(self, *, follow_symlinks: bool = True, strict: bool = True) -> bool:
        """Return True if the path points to an existing file or directory, False otherwise.

        `strict` determines whether the path must exist with the same semantic path type.
        For example (note the trailing slash):
            - Path("path/to/existing/file/").exists(strict=True) == False
              because the *directory* ".../file/" does not exist.

            - Path("path/to/existing/file/").exists(strict=False) == True
              because the path points to something which does exist on-disk.
        """
        try:
            mode = self.stat(follow_symlinks=follow_symlinks).st_mode
        except (FileNotFoundError, NotADirectoryError):
            return False

        if not strict:
            # it doesn't matter what's there, as long as it exists
            return True

        pathtype = identify_st_mode(mode)

        if self._semantic_path_type == SemanticPathType.DIRECTORY:
            return pathtype == PathType.DIRECTORY
        else:
            return pathtype not in (PathType.DIRECTORY, PathType.UNKNOWN)

    @property
    def type(self) -> PathType:
        """Return the type of the given path: e.g, REGULAR_FILE or DIRECTORY."""
        if not self.exists(follow_symlinks=False, strict=False):
            return PathType.DOES_NOT_EXIST

        return identify_st_mode(self.stat(follow_symlinks=False).st_mode)

    def is_directory(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        """Return True if the path is a directory, False otherwise. If the path does not exist, use semantic reasoning.

        If the path exists, then return whether this path points to a directory on disk.

        If the path does not exist, then:
            - return False if `must_exist` is True (mimics the behavior of pathlib.PurePath.is_dir)
            - return whether the path is semantically a directory

        Examples:
              # regardless of the value of `must_exist`
            - Path("path/to/existing/file").is_directory() == False
            - Path("path/to/existing/directory/").is_directory() == True

              # equivalent results to pathlib.Path.is_dir
            - Path("path/to/nonexistent/file").is_directory(must_exist=True) == False
            - Path("path/to/nonexistent/directory/").is_directory(must_exist=True) == False

              # with `must_exist = False` (default), use semantic reasoning
            - Path("path/to/nonexistent/file").is_directory() == False
            - Path("path/to/nonexistent/directory/").is_directory() == True

        """
        target = self.resolve() if follow_symlinks else self

        if target.type == PathType.DIRECTORY:
            return True

        if target.type == PathType.DOES_NOT_EXIST:
            if must_exist:
                return False

            return self._semantic_path_type == SemanticPathType.DIRECTORY

        return False

    def is_file(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        """Return True if the path is any file, False otherwise. If the path does not exist, use semantic reasoning.
        Note that, e.g., Path("path/to/symlink").is_file() == True because symlinks *are* files.

        If the path exists, then return whether this path points to a file on disk.

        If the path does not exist, then:
            - return False if `must_exist` is True (mimics the behavior of pathlib.PurePath.is_dir)
            - return whether the path is semantically a file

        Examples:
              # regardless of the value of `must_exist`
            - Path("path/to/existing/file").is_file() == True
            - Path("path/to/existing/directory/").is_file() == False

              # equivalent results to pathlib.Path.is_dir
            - Path("path/to/nonexistent/file").is_file(must_exist=True) == False
            - Path("path/to/nonexistent/directory/").is_file(must_exist=True) == False

              # with `must_exist = False` (default), use semantic reasoning
            - Path("path/to/nonexistent/file").is_file() == True
            - Path("path/to/nonexistent/directory/").is_file() == False
        """
        target = self.resolve() if follow_symlinks else self

        if target.type not in (PathType.DIRECTORY, PathType.UNKNOWN):
            return True

        if target.type == PathType.DOES_NOT_EXIST:
            if must_exist:
                return False

            return self._semantic_path_type == SemanticPathType.FILE

        return False

    def is_same_file(self, other: os.PathLike[str]) -> bool:
        return self._path.samefile(pathlib.Path(other))

    @overload
    def open(
        self,
        mode: Literal["r", "w", "a", "r+", "w+", "a+", "x", "x+"] = "r",
        *,
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> TextIO: ...

    @overload
    def open(
        self,
        mode: Literal["rb", "wb", "ab", "r+b", "w+b", "a+b", "xb", "x+b"],
        *,
        buffering: int = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> BinaryIO: ...

    def open(
        self,
        mode: str = "r",
        *,
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        """Open the file pointed to by the path, like builtins.open does."""
        return self._path.open(mode=mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline)

    def read_text(self, *, encoding: str = "utf-8", errors: str | None = None, newline: str | None = None) -> str:
        """Open the file pointed to in text mode, read its contents, and close the file."""
        with open(self, mode="rt", encoding=encoding, errors=errors, newline=newline) as f:
            return f.read()

    def read_lines(
        self,
        *,
        encoding: str = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ) -> list[str]:
        """Read the contents of the file, returning a list of the line contents."""
        return self.read_text(encoding=encoding, errors=errors, newline=newline).splitlines()

    def read_bytes(self) -> bytes:
        """Open the file pointed to in text mode, read its contents, and close the file."""
        with open(self, mode="rb") as f:
            return f.read()

    def write_bytes(self, data: Buffer, *, mode: Literal["w", "a"] = "w") -> int:
        """Open the file pointed to in binary mode, write `data` to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.
        """
        with open(self, mode=f"{mode}b") as f:
            return f.write(data)

    def write_text(
        self,
        data: str,
        *,
        mode: Literal["w", "a"] = "w",
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        """Open the file pointed to in text mode, write `data` to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.
        """
        with open(self, mode=mode, encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    def write_lines(
        self,
        lines: Iterable[str],
        *,
        mode: Literal["w", "a"] = "w",
        encoding: str = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        """Open the file pointed to in text mode, write the given lines to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.
        """
        with open(self, mode=mode, encoding=encoding, errors=errors, newline=newline) as f:
            f.writelines(lines)

    def write_text_atomic(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        """Write the given text to this path, ensuring that the operation is performed atomically (as one unit), which
        guarantees that on an error, the previous state of the file will be preserved.
        """
        with type(self).temporary_file() as temp_path:
            temp_path.write_text(data)

        try:
            temp_path.replace(self)
        except Exception:
            try:
                temp_path.delete()
            except OSError:
                pass
            raise

    def __iter__(self) -> Iterator[Self]:
        """Iterate over the children of the directory represented by this path.
        If this path is not a directory, OSError is raised.
        """
        return self.iterdir()

    def iterdir(self) -> Iterator[Self]:
        """Iterate over the children of the directory represented by this path.
        If this path is not a directory, OSError is raised.
        """
        for path in self._path.iterdir():
            semantics = SemanticPathType.DIRECTORY if path.is_dir() else SemanticPathType.FILE
            yield type(self)._from_pathlib_path(path, semantic_path_type=semantics)

    def copy(
        self,
        to: Self,
        *,
        follow_symlinks: bool = True,
        metadata: bool = True,
        maintain_symlinks: bool = False,
        dirs_exist_ok: bool = False,
        ignore: Iterable[str] | None = None,
    ) -> None:
        """Copy this path to the given path (`to`). Optionally, also copy metadata.
        Warning: Even with metadata=True, some metadata (e.g., file owner, ACLs) may not be guaranteed to be preserved.

        `follow_symlinks` is used when the given path is a file:
            - if False and this path is a symlink, then `to` will be created as a symlink
            - if True and this path is a symlink, then `to` will be a copy of the file this path links to

        `maintain_symlinks`, `dirs_exist_ok`, and `ignore` are used when the given path is a directory:
            - if `maintain_symlinks` is True, then symlinks in the source tree will be preserved
              as symlinks in the destination tree
            - if `maintain_symlinks` is False, then the contents of the linked files will be copied instead

            - if `dirs_exist_ok` is False and `to` already exists, FileExistsError will be raised
            - if `dirs_exist_ok` is True, then any existing directories will be overwritten

            - `ignore` should be a list of glob patterns that should be ignored when copying a directory.
               For example, when copying a project directory whilst ignoring pycache files, use `ignore=["*.pyc"]`.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy from nonexisting path: {self}")

        copy_function = shutil.copy2 if metadata else shutil.copy

        if self.is_directory():
            if ignore is None:
                ignore = tuple()

            shutil.copytree(
                self,
                to,
                copy_function=copy_function,
                symlinks=maintain_symlinks,
                dirs_exist_ok=dirs_exist_ok,
                ignore=shutil.ignore_patterns(*ignore),
            )
        else:
            copy_function(self, to, follow_symlinks=follow_symlinks)

    def copy_permissions(self, to: Self, *, follow_symlinks: bool = True) -> None:
        """Copy the permission bits from self to the other path (`to`). The file contents/owner/group are unaffected.

        If follow_symlinks is False and `self` and `to` both point to symlinks, this function will attempt to modify the
        permissions of the `to` file itself (rather than the file it points to).
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy permissions for nonexistent path: {self}")

        shutil.copymode(self, to, follow_symlinks=follow_symlinks)

    def copy_stat(self, to: Self, *, follow_symlinks: bool = True) -> None:
        """Copy permission bits, last access time, last modification time, and flags to the target path.
        On Linux, this also copies the extended attributes where possible.
        The file contents, owner, and group are unaffected.

        If follow_symlinks is False and `self` and `to` both point to symlinks, this function will operate on the
        symlinks themselves (rather than the files they point to).
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy stat for nonexistent path: {self}")

        shutil.copystat(self, to, follow_symlinks=follow_symlinks)

    def delete(self, *, recursive: bool = False, strict: bool = True, force: bool = False) -> None:
        """Delete this path (file, symlink, or directory). With `force=False`, raise an error if the path doesn't exist.

        `recursive`
            If True and the path is a physical directory, delete the entire directory tree;
            if False and the path is a physical directory, fails if the directory is nonempty unless `force` is True.

        `force`
            If True, proceed without checking for existence and suppressing FileNotFoundError/OSError on failure,
            equivalent to a best-effort delete.

            `force=True` also allows deleting nonempty directories even when `recursive=False`.

        `strict`
            Alongside `force=False`, raise FileNotFoundError if the path exists but has the wrong semantic type.
            For example, if `p = Path("path/to/file/")` is a physical file (despite its semantic type as directory),
            then `p.delete(strict=False)` will succeed, but `p.delete(strict=True)` will fail.
        """
        if not force and not self.exists(follow_symlinks=False, strict=strict):
            raise FileNotFoundError(f"Cannot delete nonexistent path: {self}")

        if self.is_directory(follow_symlinks=False):
            if recursive or force:
                shutil.rmtree(self, ignore_errors=force)
            else:
                self._path.rmdir()
        elif force:
            with suppress(FileNotFoundError):
                self._path.unlink()
        else:
            self._path.unlink()

    def move(self, to: Self, *, metadata: bool = True) -> None:
        """Recursively move this path to the given destination (`to`).
        If `to` is an existing directory, the source is placed inside it.
        If `to` exists but is not a directory, then it may be overwritten.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot move nonexistent path: {self}")

        copy_function = shutil.copy2 if metadata else shutil.copy
        shutil.move(self, to, copy_function=copy_function)

    def rename(self, to: str | os.PathLike[str], *, force: bool = True) -> Self:
        """Rename this path to the given name.

        The target `to` may be absolute or relative; if relative, it is interpreted
        relative to the current working directory (not the given path).

        It is implemented in terms of `os.rename` and thus only works for local paths.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot rename nonexistent path: {self}")

        if force:
            return self.replace(to)

        return type(self)._from_pathlib_path(self._path.rename(to), semantic_path_type=self._semantic_path_type)

    def replace(self, to: str | os.PathLike[str]) -> Self:
        """Rename this path to the given name, overwriting the target if it exists.

        The target `to` may be absolute or relative; if relative, it is interpreted
        relative to the current working directory (not the given path).
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot replace nonexistent path: {self}")

        return type(self)._from_pathlib_path(self._path.replace(to), semantic_path_type=self._semantic_path_type)

    def disk_usage(self) -> DiskUsage:
        """Return disk usage statistics on the given path, as (total, used, free). Values are given in bytes.
        (Unix) The given path must be mounted.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot report disk usage for nonexistent path: {self}")

        return DiskUsage(*shutil.disk_usage(self))

    def chown(
        self,
        user: int | str | None = None,
        group: int | str | None = None,
        *,
        follow_symlinks: bool = True,
    ) -> None:
        """Change owner `user` and/or `group` for the given path.
        `user` and `group` can be system username (str) or uid (int). At least one of them is required.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot change owner/group for nonexistent path: {self}")

        # shutil's stub files don't show None as a valid type for user/group (despite it being the default),
        # meaning that mypy complains if we try to pass it. Thus, instead of just calling shutil.chown(...) with
        # all of the args, we will just not pass them and abuse the defaults.

        target = self.resolve() if follow_symlinks else self
        match user, group:
            case None, None:
                raise ValueError("At least one of `user` and `group` must be specified.")
            case user, None:
                user = cast(int | str, user)
                shutil.chown(target, user=user)
            case None, group:
                group = cast(int | str, group)
                shutil.chown(target, group=group)
            case user, group:
                user = cast(int | str, user)
                group = cast(int | str, group)
                shutil.chown(target, user=user, group=group)

    def chmod(self, mode: int, *, follow_symlinks: bool = True) -> None:
        """Change the permissions of the given path."""
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot change permissions for nonexistent path: {self}")

        target = self.resolve() if follow_symlinks else self
        os.chmod(target, mode)

    def __contains__(self, other: str | os.PathLike[str]) -> bool:
        """Determine whether the other path is within the subpath of this path."""
        return type(self)(other).is_relative_to(self, strict=True)

    def _get_relative_depth(self, other: Self) -> int:
        """Returns the number of components in `other` relative to `self`."""
        if other not in self:
            raise ValueError(f"Path {other} is not contained within {self}.")

        if self.is_same_file(other):
            # before Python 3.12, self.relative_to(self) was Path("."), which has length 1
            return 0

        return len(other.relative_to(self).parts)

    def walk(
        self, *, top_down: bool = True, on_error: Callable[[OSError], None] | None = None
    ) -> Iterator[tuple[Self, list[str], list[str]]]:
        """Generate the file n ames in a directory tree by walking the directory tree top-down.

        For each directory in the tree rooted this path, it yields a 3-tuple (dirpath, dirnames, filenames):
            - dirpath: a Path object currently being walked
            - dirnames: a list of the names of the directories at this path
            - filenames: a list of the names of the non-directory files at this path

        If `top_down` is True, the caller can modify the dirnames and filenames lists, which will affect the
        contents of the next yielded tuple.

        If `top_down` is False, the triple for a directory is generated after the triples for all of its subdirectories.
        """
        for root_name, dirnames, filenames in os.walk(str(self), top_down, on_error):
            yield type(self)(root_name), dirnames, filenames

    def traverse(
        self,
        *,
        top_down: bool = True,
        on_error: Callable[[OSError], None] | None = None,
        follow_symlinks: bool = False,
        show_hidden: bool = True,
        max_depth: int | None = None,
        exclude_globs: Iterable[str] | None = None,
    ) -> Iterator[Self]:
        """Iterate over every item (directory and file) within the given path."""
        exclude_patterns = [re.compile(fnmatch.translate(g)) for g in exclude_globs] if exclude_globs else []

        for root_name, dirnames, filenames in os.walk(str(self), top_down, on_error, follow_symlinks):
            root = type(self)(root_name)

            if exclude_patterns:
                base = type(self)(".") if self == root else root.relative_to(self)
                dirnames[:] = [d for d in dirnames if not any(excl.match(str(base / d)) for excl in exclude_patterns)]

            if max_depth is not None:
                depth = root._get_relative_depth(self)

                if depth >= max_depth:
                    # prevent further recursion
                    dirnames.clear()

            yield root

            for filename in filenames:
                path = root / filename

                if filename.startswith(".") and not show_hidden:
                    continue

                relpath = str(path.relative_to(self))
                if exclude_patterns and any(excl.match(relpath) for excl in exclude_patterns):
                    continue

                yield path

    def find(
        self,
        pattern: str | re.Pattern[str] = "",
        *,
        glob: bool = False,
        follow_symlinks: bool = False,
        min_depth: int | None = None,
        max_depth: int | None = None,
        exclude_globs: list[str] | None = None,
        type: PathType | Iterable[PathType] | None = None,
        extension: str | None = None,
        show_hidden: bool = True,
    ) -> Iterator[Self]:
        """Return an iterator over the paths within the given path that match all of the given conditions."""

        def get_allowed_types() -> list[PathType]:
            if type is None:
                return []

            if isinstance(type, PathType):
                return [type]

            return list(type)

        def get_pattern() -> re.Pattern[str]:
            if glob and isinstance(pattern, re.Pattern):
                raise ValueError("If glob is True, pattern must be a string, not a compiled regular expression.")

            if isinstance(pattern, re.Pattern):
                return pattern

            return re.compile(fnmatch.translate(pattern) if glob else pattern)

        allowed_types = get_allowed_types()
        pattern = get_pattern()

        for path in self.traverse(
            follow_symlinks=follow_symlinks,
            show_hidden=show_hidden,
            max_depth=max_depth,
            exclude_globs=exclude_globs,
        ):
            if not pattern.search(path.name):
                continue

            if min_depth is not None and min_depth > path._get_relative_depth(self):
                continue

            if allowed_types and path.type not in allowed_types:
                continue

            if extension and path.suffix != f".{extension.lstrip('.')}":
                continue

            yield path

    def touch(self, *, mode: int = 0o666, exist_ok: bool = False) -> None:
        """Create an empty file at this path.

        If `mode` is given, it is combined with the process's umask value to determine file mode and access flags.

        If the file exists, the function succeeds when `exist_ok` is true (and its modification time is updated);
        otherwise, FileExistsError is raised.
        """
        self._path.touch(mode=mode, exist_ok=exist_ok)

    def mkdir(self, *, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        """Create a directory at this path.

        If `mode` is given, it is combined with the process's umask value to determine file mode and access flags.

        If `parents` is True, any missing parent directories are created as needed, with the default permissions
        (without taking `mode` into account, which mimics POSIX `mkdir -p`). If `parents` is False, any missing
        directories cause FileNotFoundError to be raised.

        If `exist_ok` is False, FileExistsError is not raised if the target directory already exists;
        if `exist_ok` is True, the error is not raised unless the path itself exists and is not a directory.
        """
        self._path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    def symlink_to(self, target: str | os.PathLike[str], *, target_is_directory: bool = False) -> None:
        """Create a symbolic link to the target file or directory."""
        self._path.symlink_to(target, target_is_directory=target_is_directory)

    def hardlink_to(self, target: str | os.PathLike[str]) -> None:
        """Create a hard link to the target file."""
        self._path.link_to(target)

    def owner(self, *, follow_symlinks: bool = True) -> str:
        """Return the owner name of the file owner."""
        if os.name == "nt":
            raise OSError("Owner name cannot be determined on this platform.")

        try:
            import pwd
        except ImportError:
            # collapse the NotImplementedError/pathlib.UnsupportedOperation dichotomy
            raise OSError("Owner name cannot be determined on this platform.")

        return pwd.getpwuid(self.owner_id(follow_symlinks=follow_symlinks)).pw_name

    def owner_id(self, *, follow_symlinks: bool = True) -> int:
        """Return the user ID of the file owner."""
        return self.stat(follow_symlinks=follow_symlinks).st_uid

    def group(self, *, follow_symlinks: bool = True) -> str:
        """Return the group name of the file owner."""
        if os.name == "nt":
            raise OSError("Group name cannot be determined on this platform.")

        try:
            import grp
        except ImportError:
            # collapse the NotImplementedError/pathlib.UnsupportedOperation dichotomy
            raise OSError("Group name cannot be determined on this platform.")

        return grp.getgrgid(self.group_id(follow_symlinks=follow_symlinks)).gr_name

    def group_id(self, *, follow_symlinks: bool = True) -> int:
        """Return the group ID of the file owner."""
        return self.stat(follow_symlinks=follow_symlinks).st_gid

    def inode(self, *, follow_symlinks: bool = True) -> int:
        """Return the inode number of the file."""
        return self.stat(follow_symlinks=follow_symlinks).st_ino

    def device(self, *, follow_symlinks: bool = True) -> int:
        """Return the device number of the file."""
        return self.stat(follow_symlinks=follow_symlinks).st_dev

    def hardlinks(self, *, follow_symlinks: bool = True) -> int:
        """Return the number of hard links to the file."""
        return self.stat(follow_symlinks=follow_symlinks).st_nlink

    def size(
        self,
        *,
        follow_symlinks: bool = True,
        unit: DecimalSizePrefix | BinarySizePrefix = "B",
    ) -> float:
        """Return the size of the file, in bytes."""
        if unit not in SIZE_PREFIX_CONVERSIONS.keys():
            raise ValueError(f"Invalid size unit: {unit}")

        factor = SIZE_PREFIX_CONVERSIONS[unit]

        if self.type == PathType.DIRECTORY:
            total = sum(child.size(follow_symlinks=follow_symlinks, unit="B") for child in self)
            return total / factor

        return self.stat(follow_symlinks=follow_symlinks).st_size / factor

    def accessed_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last access time of the file."""
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_atime)

    def modified_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last modification time of the file."""
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_mtime)

    def metadata_modified_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last metadata change time of the file."""
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_ctime)

    def _created_time_windows(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file (Windows implementation)."""
        attr = "st_ctime" if sys.version_info < (3, 12) else "st_birthtime"
        stat_info = self.stat(follow_symlinks=follow_symlinks)

        ts = getattr(stat_info, attr)
        return datetime.fromtimestamp(ts)

    def _created_time_posix(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file (POSIX implementation)."""
        try:
            # st_birthtime is not always available
            # "type ignore" is used because mypy cannot determine whether it exists
            ts = self.stat(follow_symlinks=follow_symlinks).st_birthtime  # type: ignore
        except AttributeError:
            raise OSError("Creation time cannot be determined on this platform.")

        return datetime.fromtimestamp(ts)

    def created_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file."""

        if os.name == "nt":
            return self._created_time_windows(follow_symlinks=follow_symlinks)

        return self._created_time_posix(follow_symlinks=follow_symlinks)
