from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
import fnmatch
from functools import total_ordering, wraps
import os
import os.path
import pathlib
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, BinaryIO, IO, Literal, overload, ParamSpec, TextIO, TypeVar

if sys.version_info >= (3, 11):
    from collections.abc import Buffer
    from typing import Self
else:
    from typing_extensions import Buffer, Self

from . import usergroup
from .disk_usage import DiskUsage
from .pathtype import identify_st_mode, PathType
from .semantic_pathtype import identify_semantic_path_type, SemanticPathLike, SemanticPathType
from .size_unit_prefixes import BinarySizePrefix, DecimalSizePrefix, SIZE_PREFIX_CONVERSIONS

_P = TypeVar("_P", bound="Path")
_R = TypeVar("_R")
_S = ParamSpec("_S")


def access_error_handler(func: Callable[_S, _R]) -> Callable[_S, _R]:
    """Wrap methods that access paths to catch permission errors and file not found errors."""

    @wraps(func)
    def wrapper(*args: _S.args, **kwargs: _S.kwargs) -> _R:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError:
            raise FileNotFoundError(f"Path does not exist: {args[0]}. Failed during {func.__name__}.")
        except PermissionError:
            raise PermissionError(f"Permission denied: {args[0]}. Failed during {func.__name__}.")
        except OSError as e:
            raise OSError(f"Failed to access {args[0]} during {func.__name__}. Reason: {e}")

    return wrapper


@total_ordering
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
        """Return the string representation of the path.

        This method makes `Path` objects compatible with os.PathLike.

        :returns: The string representation of the path
        """
        return self._path.__fspath__()

    def __semantic_path_type__(self) -> SemanticPathType:
        """Return the semantic path type of this path.

        :returns: The semantic path type of this path
        """
        return self._semantic_path_type

    def __str__(self) -> str:
        """Return a human-readable string representation of the path.
        This representation is normalized, with "." and ".." being resolved.

        :returns: The human-readable string representation of the path
        """
        return os.path.normpath(str(self._path)) + self._semantic_path_type.value

    def __repr__(self) -> str:
        """Return a string representation of the path.

        :returns: The string representation of the path
        """
        return f"{self.__class__.__name__}({self._path}{self._semantic_path_type.value})"

    def __eq__(self, other: object) -> bool:
        """Return whether this path is equal to another path.

        :param other: The path to compare to

        :returns: True if the paths are equal, False otherwise
        """
        if isinstance(other, type(self)):
            return str(self) == str(other)

        if isinstance(other, pathlib.Path):
            return self._path == other

        return NotImplemented

    def __lt__(self, other: object) -> bool:
        """Return whether this path should sort before the other path. This check is lexicographic.

        :param other: The path to compare to

        :returns: True if this path should sort before the other path, False otherwise
        """
        if isinstance(other, type(self)):
            return str(self) < str(other)

        if isinstance(other, pathlib.Path):
            return self._path < other

        return NotImplemented

    def __hash__(self) -> int:
        """Return the hash of the path.

        :returns: The hash value of the path
        """
        return hash(self._path)

    @classmethod
    def _identify_semantic_path_type(cls, path: str | SemanticPathLike) -> SemanticPathType:
        """Determine the semantic path type of a given path, where possible.

        :param path: The path to determine the semantic path type of

        :returns: The semantic path type of the path

        :raises TypeError: If the path is not a str or SemanticPathLike
        """
        if isinstance(path, SemanticPathLike):
            return path.__semantic_path_type__()

        if isinstance(path, str):
            return identify_semantic_path_type(path)

        raise TypeError(f"expected str or SemanticPathLike, not {type(path)}")

    @classmethod
    def _from_pathlib_path(cls, path: pathlib.Path, *, semantic_path_type: SemanticPathType) -> Self:
        """Return an instance of this class from a pathlib.Path instance, avoiding the initialization overhead.

        This should only be used internally.

        :param path: The pathlib.Path instance to use
        :param semantic_path_type: The semantic path type to assign

        :returns: An instance of this class with the given path and semantic path type.
        """
        inst = cls.__new__(cls)
        inst._path = path
        inst._semantic_path_type = semantic_path_type
        return inst

    @classmethod
    def home(cls) -> Self:
        """Return a new path object for the user's home directory.

        :returns: A new path object pointing to user's home directory
        """
        return cls._from_pathlib_path(pathlib.Path.home(), semantic_path_type=SemanticPathType.DIRECTORY)

    def expand_user(self) -> Self:
        """Return a new path object with the user's home directory expanded.

        >>> Path("~/foo/bar/baz.txt").expand_user()
        Path("/home/user/foo/bar/baz.txt")

        :returns: A new path object to this same path, with the home directory expanded.
        """
        return type(self)._from_pathlib_path(self._path.expanduser(), semantic_path_type=self._semantic_path_type)

    @classmethod
    def cwd(cls) -> Self:
        """Return a new path object for the current working directory.

        :returns: A new path object pointing to the current working directory
        """
        return cls._from_pathlib_path(pathlib.Path.cwd(), semantic_path_type=SemanticPathType.DIRECTORY)

    @classmethod
    def from_uri(cls, uri: str) -> Self:
        """Return a new path object from parsing a file URI.

        >>> Path.from_uri("file:///foo/bar/baz.txt")
        Path("/foo/bar/baz.txt")

        :param uri: The file URI to parse

        :returns: A new path object from parsing the file URI

        :raises ValueError: If the URI is invalid or the path is not absolute
        """
        if not (match := re.match(r"file://(.*)", uri)):
            raise ValueError(f"invalid file URI: {uri}")

        filepath = match.group(1)
        semantic_path_type = cls._identify_semantic_path_type(filepath)
        return cls._from_pathlib_path(pathlib.Path(filepath), semantic_path_type=semantic_path_type)

    def as_uri(self) -> str:
        """Return a string representing the path as a file URI.

        >>> Path("/foo/bar/baz.txt").as_uri()
        "file:///foo/bar/baz.txt"

        :returns: A string representing the path as a file URI

        :raises ValueError: If the path is not absolute
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
        """Return a path pointing to a temporary file. This should be used within a `with` block.
        Unless `delete=False`, the temporary file is automatically deleted when the context manager exits.

        >>> with Path.temporary_file() as p:
        ...     p.write_text("Hello, world!")
        ...     assert p.read_text() == "Hello, world!"
        >>> assert not p.exists()

        >>> with Path.temporary_file(delete=False) as p:
        ...     p.write_text("Hello, world!")
        ...     assert p.read_text() == "Hello, world!"
        >>> assert p.exists()

        :param suffix: If provided, the suffix to use for the temporary file
        :param prefix: If provided, the prefix to use for the temporary file
        :param parent: If provided, the parent directory to use for the temporary file
        :param delete: Whether to delete the temporary file when the context manager exits (default: True)

        :yields: A new path object pointing to the temporary file
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
        """Return a path pointing to a temporary directory. This should be used within a `with` block.
        Unless `delete=False`, the temporary directory is automatically deleted when the context manager exits.

        >>> with Path.temporary_directory() as p:
        ...     (p / "foo.txt").write_text("Hello, world!")
        >>> assert not p.exists()

        >>> with Path.temporary_directory(delete=False) as p:
        ...     (p / "foo.txt").write_text("Hello, world!")
        >>> assert p.exists()

        >>> with Path.temporary_directory() as p:
        ...     with Path.temporary_file(parent=p) as f:
        ...         f.write_text("Hello, world!")
        >>> assert not p.exists()
        >>> assert not f.exists()

        :param suffix: If provided, the suffix to use for the temporary directory
        :param prefix: If provided, the prefix to use for the temporary directory
        :param parent: If provided, the parent directory to use for the temporary directory
        :param delete: Whether to delete the temporary directory when the context manager exits (default: True)

        :yields: A new path object pointing to the temporary directory
        """
        temp_dir = cls(tempfile.mkdtemp(suffix=suffix, prefix=prefix, dir=parent) + os.path.sep)

        try:
            yield temp_dir
        finally:
            if delete:
                temp_dir.delete(force=True)

    def __truediv__(self, other: str | os.PathLike[str]) -> Self:
        """Return a new path by joining the given path with this path.

        For convenience, this does not enforce semantic meaning of `self` as a directory.
        Thus, `Path("/foo") / "bar.jpg" / "baz.txt"` succeeds, yielding `Path("/foo/bar.jpg/baz.txt")`.
        This removes the need for the doubled slashes in `Path("foo/") / "bar.jpg/" / "baz.txt"`.

        >>> Path("/foo/bar") / "baz.txt"
        Path('/foo/bar/baz.txt')

        :param other: The path to join with this path
        :returns: A new path object to this same path, joined with the given path
        """
        if not isinstance(other, (str, SemanticPathLike)):
            return NotImplemented

        semantic_path_type = self._identify_semantic_path_type(other)
        return type(self)._from_pathlib_path(self._path / other, semantic_path_type=semantic_path_type)

    @property
    def parts(self) -> tuple[str, ...]:
        """Return a tuple of the path's components.

        >>> Path("/foo/bar/baz.txt").parts
        ('/', 'foo/', 'bar/', 'baz.txt')

        :returns: A tuple of the path's component names, as strings
        """
        parts = list(self._path.parts)

        for i, part in enumerate(parts[:-1]):
            if part and not part.endswith(os.path.sep):
                # these are all intermediate directories and should be rendered as such
                parts[i] = f"{part}{os.path.sep}"

        if parts and not parts[-1].endswith(os.path.sep):
            # the final component
            parts[-1] = f"{parts[-1]}{self._semantic_path_type.value}"

        return tuple(parts)

    @property
    def components(self) -> tuple[str, ...]:
        """Return a tuple of the path's components. This is an alias for Path.parts.

        >>> Path("/foo/bar/baz.txt").components
        ('/', 'foo/', 'bar/', 'baz.txt')

        :returns: A tuple of the path's component names, as strings
        """
        return self.parts

    @property
    def drive(self) -> str:
        """Return a string representing the drive (e.g., "C:" on Windows).

        >>> Path("C:\\Users\\Emily\\Documents\\foo.txt").drive
        'C:'

        >>> Path("/foo/bar/baz.txt").drive
        ''

        UNC shares are also considered drives:

        >>> Path('//host/share/foo.txt').drive
        '\\\\host\\share'

        :returns: A string representing the drive
        """
        return self._path.drive

    @property
    def root(self) -> str:
        """Return a string representing the path's root (if any).

        >>> Path("C:\\Users\\Emily\\Documents\\foo.txt").root
        '\\'

        >>> Path("/foo/bar/baz.txt").root
        '/'

        UNC shares always have a root:
        >>> Path('//host/share/foo.txt').root
        '\\'

        :returns: A string representing the root
        """
        return self._path.root

    @property
    def anchor(self) -> str:
        """The concatenation of the drive and root.

        >>> Path("C:\\Users\\Emily\\Documents\\foo.txt").anchor
        'C:\\'

        >>> Path("/foo/bar/baz.txt").anchor
        '/'

        UNC shares always have an anchor:
        >>> Path('//host/share/foo.txt').anchor
        '\\\\host\\share\\'

        :returns: A string representing the anchor (drive + root)
        """
        return self._path.anchor

    def _get_parents_impl(self: _P) -> tuple[_P, ...]:
        """Return a tuple of the path's parent directories.
        This is an internal method provided as an implementation detail for the parents property
        in order to work around known mypy limitations. Hence the unusual typing of `self: _P.`

        :returns: A tuple of the path's parent directories
        """
        return tuple(
            type(self)._from_pathlib_path(p, semantic_path_type=SemanticPathType.DIRECTORY) for p in self._path.parents
        )

    @property
    def parents(self) -> tuple[Self, ...]:
        """Return a tuple of the path's parent directories, in order from the immediate parent to the root.

        >>> Path("/foo/bar/baz.txt").parents
        (Path('/foo/bar/'), Path('/foo/'), Path('/'))

        :returns: A tuple of the path's parent directories
        """
        return self._get_parents_impl()

    @property
    def parent(self) -> Self:
        """Return the path's parent directory.

        >>> Path("/foo/bar/baz.txt").parent
        Path('/foo/bar/')

        :returns: The path's immediate parent directory
        """
        return type(self)._from_pathlib_path(self._path.parent, semantic_path_type=SemanticPathType.DIRECTORY)

    @property
    def name(self) -> str:
        """Return a string representing the path's last component, excluding the drive and root.

        >>> Path("/foo/bar/baz.txt").name
        'baz.txt'

        :returns: A string representing the path's last component
        """
        return self._path.name

    @property
    def suffix(self) -> str:
        """Return a string representing the path's last component's suffix.

        >>> Path("/foo/bar/baz.txt").suffix
        '.txt'

        If the file has no suffix, returns an empty string:
        >>> Path("/foo/bar/baz").suffix
        ''

        If the file has multiple suffixes, return the final one:
        >>> Path("/foo/bar/baz.tar.gz").suffix
        '.gz'

        As in pathlib 3.14, a literal "." suffix is allowed:
        >>> Path("/foo/bar/baz.").suffix
        '.'

        :returns: A string representing the path's last component's suffix
        """
        if re.fullmatch(r"\.+", str(self)):
            # special case: when the path is all dots ("...."), the suffix is always empty
            return ""

        if str(self).endswith("."):
            # when the path ends with a dot (but is not all dots), the suffix is "."
            return "."

        return self._path.suffix

    @property
    def suffixes(self) -> list[str]:
        """Return a list of strings representing the path's last component's suffixes.

        >>> Path("/foo/bar/baz.txt").suffixes
        ['.txt']

        >>> Path("/foo/bar/baz").suffixes
        []

        >>> Path("/foo/bar/baz.tar.gz").suffixes
        ['.tar', '.gz']

        >>> Path("/foo/bar/baz.").suffixes
        ['.']

        :returns: A list of strings representing the path's last component's suffixes
        """
        if re.fullmatch(r"\.+", str(self)):
            # special case: when the path is all dots ("...."), the suffix is always empty
            return []

        if str(self).endswith("."):
            # when the path ends with a dot (but is not all dots), the trailing suffix is "."
            return self.with_name(self.name.rstrip(".")).suffixes + ["."]

        return self._path.suffixes

    @property
    def stem(self) -> str:
        """Return a string representing the path's last component, excluding the final suffix.

        >>> Path("/foo/bar/baz.txt").stem
        'baz'

        >>> Path("/foo/bar/baz").stem
        'baz'

        If the file has multiple suffixes, the stem maintains all but the final one:
        >>> Path("/foo/bar/baz.tar.gz").stem
        'baz.tar'

        :returns: A string representing the path's last component without the final suffix
        """
        return self._path.stem

    @access_error_handler
    def __abs__(self) -> Self:
        """Return a new path with the path made absolute, without normalizing or resolving symlinks.
        `abs(path)` is equivalent to `path.absolute()`.

        >>> abs(Path("/foo/bar/baz.txt"))
        Path('/foo/bar/baz.txt')

        If the path is relative, it will be made absolute relative to the working directory (assumed here as foo/bar/):
        >>> abs(Path("a/b/c.txt"))
        Path('/foo/bar/a/b/c.txt')

        :returns: A new path with the path made absolute
        """
        return self.absolute()

    def absolute(self) -> Self:
        """Return a new path with the path made absolute, without normalizing or resolving symlinks.

        >>> Path("/foo/bar/baz.txt").absolute()
        Path('/foo/bar/baz.txt')

        If the path is relative, it will be made absolute relative to the working directory (assumed here as foo/bar/):
        >>> Path("a/b/c.txt").absolute()
        Path('/foo/bar/a/b/c.txt')

        :returns: A new path with the path made absolute
        """
        return type(self)._from_pathlib_path(self._path.absolute(), semantic_path_type=self._semantic_path_type)

    def is_absolute(self) -> bool:
        """Return whether the path is absolute or not (i.e., includes a root and, as allowed, a drive).

        >>> Path("/foo/bar/baz.txt").is_absolute()
        True

        >>> Path("a/b/c.txt").is_absolute()
        False

        :returns: True if the path is absolute, False otherwise
        """
        return self._path.is_absolute()

    @access_error_handler
    def resolve(self, *, strict: bool = False) -> Self:
        """Return a new absolute path with all symlinks resolved.

        If the path does not point to a symlink, this is equivalent to `path.absolute()`.
        >>> Path("/foo/bar/baz.txt").resolve()
        Path('/foo/bar/baz.txt')

        If the path does point to a symlink, then the symlink is followed:
        >>> Path("/foo/bar/symlink-to-baz.txt").resolve()
        Path('/foo/bar/baz.txt')

        :param strict:
            If True and a path does not exist or a symlink is encountered, raise OSError;
            if False, then the path is resolved as far as possible and any remaineder is appended
            without checking whether it exists.

        :returns: A new path with all symlinks resolved

        :raises OSError: If `strict` is True and the path does not exist or a symlink loop is encountered
        """
        try:
            # resolve the path using pathlib.Path, then determine the semantic path type by querying what was there
            resolved = self._path.resolve(strict=strict)
            semantic_pathtype = SemanticPathType.DIRECTORY if resolved.is_dir() else SemanticPathType.FILE
        except FileNotFoundError:
            # fall back, preserving the semantic path type of this path
            resolved = self._path.absolute()
            semantic_pathtype = self._semantic_path_type

        return type(self)._from_pathlib_path(resolved, semantic_path_type=semantic_pathtype)

    @access_error_handler
    def conform_to_filesystem(self) -> Self:
        """Return a new path that semantically matches the path on the filesystem while normalizing the path.

        >>> p = Path("/path/to/existing/file/")  # note the trailing slash
        >>> p._semantic_path_type
        SemanticPathType.DIRECTORY

        >>> p.conform_to_filesystem()     # note the lack of trailing slash
        Path(""/path/to/existing/file)
        >>> p.conform_to_filesystem()._semantic_path_type
        SemanticPathType.FILE

        If the path does not exist, then the path is normalized, but the semantic type is unchanged:

        :returns: A new path that semantically matches the path on the filesystem
        """
        target = pathlib.Path(os.path.normpath(str(self)))

        try:
            # resolve the semantic type by checking the path on the filesystem
            semantic_pathtype = SemanticPathType.DIRECTORY if target.is_dir() else SemanticPathType.FILE
        except FileNotFoundError:
            # fall back to using the existing path semantics
            semantic_pathtype = self._semantic_path_type

        return type(self)._from_pathlib_path(target, semantic_path_type=semantic_pathtype)

    @access_error_handler
    def read_link(self) -> Self:
        """Return a new path representing the target of a symbolic link.

        >>> Path("/path/to/symlink").read_link()
        Path("/path/to/target")

        :returns: A new path representing the target of a symbolic link

        :raises FileNotFoundError: If the path does not exist
        :raises OSError: If the path is not a symbolic link
        """
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

    @access_error_handler
    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        """Return an os.stat_result object containing information about this path, like os.stat.
        The result is looked up at each call to this method.

        Use `follow_symlinks=False` to stat a symlink itself.

        :param follow_symlinks:
            If True and the path is a symbolic link, then stat the target of the link;
            if False and the path is a symbolic link, then stat the symlink itself.

            This parameter has no effect is the path is not a symbolic link.

        :returns: An os.stat_result object containing information about the path

        :raises FileNotFoundError: If the path does not exist
        """
        return self._path.stat(follow_symlinks=follow_symlinks)

    @access_error_handler
    def is_relative_to(self, other: str | os.PathLike[str], *, strict: bool = False) -> bool:
        """Return whether the path is relative to another path.

        >>> Path("/path/to/file").is_relative_to("/path/to")
        True

        >>> Path("/path/to/file").is_relative_to("/path/to/another/place")
        False

        If strict is False, this method is purely string-based and doesn't access the filesystem.
        Note that Path("/path/to/..") is the same path on the filesystem as `Path("/path/").
        >>> Path("/path/to/..").is_relative_to("/path/to/")
        True

        >>> Path("/path/to/..").is_relative_to("/path/to", strict=True)
        False

        :param other:
            The path to compare against

        :param strict:
            If False, this method is purely string-based and doesn't access the filesystem, which is faster
            but can give incorrect results with nonnormalized paths;
            If True, the paths are resolved and handled appropriately.

        :returns: True if the path is relative to (contained within) the path represented by `other`, False otherwise
        """
        if strict:
            target, root = self._path.resolve(), pathlib.Path(other).resolve()
        else:
            target, root = self._path, pathlib.Path(other)

        return target.is_relative_to(root)

    @access_error_handler
    def relative_to(self, other: str | os.PathLike[str], *, strict: bool = False) -> Self:
        """Compute a version of this path relative to the path represented by `other`.

        >>> Path("/path/to/file").relative_to("/path/to")
        Path("file")

        >>> Path("/path/to/file").relative_to("/path/to/another/place")
        ValueError('/path/to/file' is not in the subpath of '/path/to/another/place')

        If strict is False, this method is purely string-based and doesn't access the filesystem.
        Note that Path("/path/to/..") is the same path on the filesystem as `Path("/path/").
        >>> Path("/path/to/..").relative_to("/path/to/")
        Path('..')

        >>> Path("/path/to/..").relative_to("/path/to", strict=True)
        ValueError('/path/' is not in the subpath of '/path/to/another/place')

        :param other:
            The path to compare against

        :param strict:
            If False, this method is purely string-based and doesn't access the filesystem, which is faster
            but can give incorrect results with nonnormalized paths;
            If True, the paths are resolved and handled appropriately.

        :returns: The relative path from `other` to `self`

        :raises ValueError: If the path is not relative to (contained within) the path represented by `other`
        """
        if strict:
            target, root = self._path.resolve(), pathlib.Path(other).resolve()
        else:
            target, root = self._path, pathlib.Path(other)

        return type(self)._from_pathlib_path(target.relative_to(root), semantic_path_type=self._semantic_path_type)

    def is_reserved(self) -> bool:
        """Return True if the path is reserved on the current platform.

        On Unix, this always returns False.
        >>> Path("/path/to/file").is_reserved()
        False

        >>> Path("C:\\Users\\Emily\\Documents\\foo.txt").is_reserved()
        False

        >> Path("C:\\Users\\Emily\\Documents\\CON").is_reserved()
        True

        :returns: True if the path is reserved on the current platform, False otherwise
        """
        if sys.version_info < (3, 13):
            return self._path.is_reserved()

        return os.path.isreserved(self)

    def join_path(self, *other: str | os.PathLike[str]) -> Self:
        """Return a new path by joining the given path with this path.

        >>> Path("/path/to").join_path("file.txt")
        Path("/path/to/file.txt")

        This may be more convenient for constructing a long path than using the normal `/` operator:
        >>> Path("/path/").join_path("to", "subdir1", "subdir2", "file.txt")
        Path("/path/to/subdir1/subdir2/file.txt")

        >>> Path("/path/") / "to" / "subdir1" / "subdir2" / "file.txt"
        Path("/path/to/subdir1/subdir2/file.txt")

        :param other: Segments of the path to join to this path

        :returns: A new path by joining the given path with this path

        :raises TypeError: If the tail element of other is semantically ambiguous (i.e., is not str or SemanticPathLike)
        """
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

    def match(self, pattern: str | re.Pattern[str], *, full: bool = False, case_sensitive: bool = True) -> bool:
        """Match this path against the provided regex pattern. Returns True if the path matches the pattern.

        .. warning::
            This method uses **regular expressions** for pattern matching and thus does not behave like
            :py:meth:`pathlib.PurePath.match` (which uses glob patterns).

            For glob matching functionality (e.g., matching `*.py`), use :py:meth:`.glob_match`
            (e.g., `path.glob_match("*.py")`).

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"/path/to/logs/log-2025-\d{2}-\d{2}\.txt")
        True

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"log-2025-\d{2}-\d{2}\.txt", full=False)
        True

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"log-2025-\d{2}-\d{2}\.txt", full=True)
        False

        :param pattern:
            The regex pattern to match against

        :param full:
            If True, then the pattern must match the full path (uses re.fullmatch under the hood);
            if False, then the pattern need match only part of the path (uses re.search under the hood)

        :param case_sensitive:
            If True, then the regex pattern is matched exactly, case-sensitively;
            if False, then the matching is performed while ignoring case (re.IGNORECASE)

        :returns: True if the path matches the pattern, False otherwise
        """
        match_func = re.fullmatch if full else re.search
        flags = re.IGNORECASE if not case_sensitive else 0
        return match_func(pattern, str(self), flags=flags) is not None

    def glob_match(self, glob: str, *, full: bool = False, case_sensitive: bool = True) -> bool:
        """Match this path against the provided glob pattern. Returns True if the path matches the pattern.

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"/path/to/logs/log-2025-*.txt")
        True

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"log-2025-*.txt", full=False)
        True

        >>> Path("/path/to/logs/log-2025-01-01.txt").match(r"log-2025-*.txt", full=True)
        False

        :param glob:
            The glob pattern to match against

        :param full:
            If True, then the pattern must match the full path (uses re.fullmatch under the hood);
            if False, then the pattern need match only part of the path (uses re.search under the hood)

        :param case_sensitive:
            If True, then the glob pattern is matched exactly, case-sensitively;
            if False, then the matching is performed while ignoring case (re.IGNORECASE)

        :returns: True if the path matches the pattern, False otherwise
        """
        return self.match(fnmatch.translate(glob), full=full, case_sensitive=case_sensitive)

    def with_name(self, name: str) -> Self:
        """Return a path with the name (last path component) changed to `name`.

        >>> Path("/path/to/file.txt").with_name("file2.txt")
        Path("/path/to/file2.txt")

        :param name: The new file name.

        :returns: A new path with the name (last path component) changed

        :raises ValueError: If the original path doesn't have a name or the new name is empty or invalid.
        """
        return type(self)._from_pathlib_path(self._path.with_name(name), semantic_path_type=self._semantic_path_type)

    def with_stem(self, stem: str) -> Self:
        """Return a path with the file stem changed to `stem`.

        >>> Path("/path/to/file.txt").with_stem("file2")
        Path("/path/to/file2.txt")

        :param stem: The new file stem.

        :returns: A new path with the stem changed

        :raises ValueError: If the original path doesn't have a name or the new stem is empty or invalid.
        """
        return type(self)._from_pathlib_path(self._path.with_stem(stem), semantic_path_type=self._semantic_path_type)

    def with_suffix(self, suffix: str) -> Self:
        """Return a path with the file suffix changed to `suffix`.

        >>> Path("/path/to/file.txt").with_suffix(".jpg")
        Path("/path/to/file.jpg")

        If the new suffix is empty, the original suffix is removed:
        >>> Path("/path/to/file.txt").with_suffix("")
        Path("/path/to/file")

        If the original path has no suffix, the new suffix is added:
        >>> Path("/path/to/file").with_suffix(".jpg")
        Path("/path/to/file.jpg")

        If the given suffix has multiple components, they are all used.
        >>> Path("/path/to/file.txt").with_suffix(".tar.gz")
        Path("/path/to/file.tar.gz")

        If the path already has multiple suffixes, only the final one is changed:
        >>> Path("/path/to/file.tar.gz").with_suffix(".jpg")
        Path("/path/to/file.tar.jpg")
        >>> Path("/path/to/file.tar.gz").with_suffix("")
        Path("/path/to/file.tar")

        The suffix may be the string ".", in which case, it is used literally:
        >>> Path("/path/to/file.txt").with_suffix(".")
        Path("/path/to/file.")

        :param suffix: The new file suffix.

        :returns: A new path with the suffix changed
        """
        if suffix == ".":
            p = type(self)(f"{self._path.with_suffix('')}.")
            p._semantic_path_type = self._semantic_path_type
            return p

        return type(self)._from_pathlib_path(
            self._path.with_suffix(suffix), semantic_path_type=self._semantic_path_type
        )

    @access_error_handler
    def exists(self, *, follow_symlinks: bool = True, strict: bool = True) -> bool:
        """Return True if the path points to an existing file or directory, False otherwise.

        >>> Path("/path/to/existing/file").exists()
        True

        >>> Path("/path/to/nonexisting/file").exists()
        False

        >>> Path("/path/to/broken/symlink").exists()
        False

        >>> Path("/path/to/broken/symlink").exists(follow_symlinks=False)
        True

        With strict=True (default), check if the path exists with the same semantic path type.
        This returns False because the path should be a directory, but the physical location exists as a file.
        >>> Path("/path/to/existing/file/").exists()
        False

        >>> Path("/path/to/existing/file/").exists(strict=False)
        False

        :param follow_symlinks:
            If True and the path is a symlink, then return whether the target of the symlink exists;
            if False, then return whether this path exists (symlink or otherwise).

        :param strict:
            If True, then the path must exist with the same semantic path type.

            >>> Path("/path/to/existing/file/").exists(strict=True)  # because the *directory* .../file/ doesn't exist
            False

            >>> Path("/path/to/existing/file/").exists(strict=False)  # because the path points to *something*
            True

        :returns: True if the path exists, False otherwise
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
    @access_error_handler
    def type(self) -> PathType:
        """Return the type of the given path: e.g, REGULAR_FILE or DIRECTORY.

        >>> Path("/path/to/regular/file").type
        PathType.REGULAR_FILE

        >>> Path("/path/to/directory/").type
        PathType.DIRECTORY

        >>> Path("/path/to/symlink").type
        PathType.SYMLINK

        >>> Path("/path/to/nonexistent/file").type
        PathType.DOES_NOT_EXIST

        :returns: The type of the path (PathType.DOES_NOT_EXIST if the path doesn't exist)

        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        if not self.exists(follow_symlinks=False, strict=False):
            return PathType.DOES_NOT_EXIST

        return identify_st_mode(self.stat(follow_symlinks=False).st_mode)

    @access_error_handler
    def is_directory(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        """Return True if the path is a directory, False otherwise. If the path does not exist, use semantic reasoning.

        If the path exists, then return whether this path points to a directory on disk.
        >>> Path("path/to/existing/file").is_directory()
        False
        >>> Path("/path/to/existing/directory/").is_directory()
        True
        >>> Path("/path/to/existing/directory").is_directory()  # semantically a file, but is a directory on disk
        True

        If the path does not exist and `must_exist` is True, return False. (matches pathlib.Path.is_dir):
        >>> Path("/path/to/nonexisting/directory/").is_directory(must_exist=True)
        False

        If the path does not exist and `must_exist` is False, return whether the path is semantically a directory:
        >>> Path("/path/to/nonexisting/file").is_directory()
        False
        >>> Path("/path/to/nonexisting/directory/").is_directory()
        True

        :param follow_symlinks:
            If True and the path is a symlink, then return whether the target of the symlink is a directory;
            if False, then return whether this path is a directory (symlink or otherwise).
        :param must_exist:
            If True, then this method returns False if the path does not exist;
            if False, then this method returns whether the path is semantically a directory.

        :returns: True if the path is a directory, False otherwise

        :raises OSError: If the path cannot be accessed due to, e.g., permission errors.
        """
        target = self.resolve() if follow_symlinks else self

        if target.type == PathType.DIRECTORY:
            return True

        if target.type == PathType.DOES_NOT_EXIST:
            if must_exist:
                return False

            return self._semantic_path_type == SemanticPathType.DIRECTORY

        return False

    @access_error_handler
    def is_file(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        """Return True if the path is any file, False otherwise. If the path does not exist, use semantic reasoning.

        ..warning ::
            This method does not distinguish between different types of files (e.g., regular files and symlinks both
            return `True`), which is different from `pathlib.Path.is_file`, which checks if the path is an **existing
            regular file**, specifically.

            `Path("path/to/symlink").is_file() == True` because symlinks *are* files.

            For the `pathlib.Path.is_file` behavior, use `path.type == PathType.REGULAR_FILE`.

        If the path exists, then return whether this path points to a file on disk.
        >>> Path("path/to/existing/file").is_file()
        True
        >>> Path("/path/to/existing/directory/").is_file()
        False

        If the path does not exist and `must_exist` is True, return False. (matches pathlib.Path.is_file):
        >>> Path("/path/to/nonexisting/file").is_file(must_exist=True)
        False

        If the path does not exist and `must_exist` is False, return whether the path is semantically a file:
        >>> Path("/path/to/nonexisting/file").is_file()
        True
        >>> Path("/path/to/nonexisting/directory/").is_file()
        False

        :param follow_symlinks:
            If True and the path is a symlink, then return whether the target of the symlink is a file;
            if False, then return whether this path is a file (symlink or otherwise).
        :param must_exist:
            If True, then this method returns False if the path does not exist;
            if False, then this method returns whether the path is semantically a file.

        :returns: True if the path is a file, False otherwise

        :raises OSError: If the path cannot be accessed due to, e.g., permission errors.
        """
        target = self.resolve() if follow_symlinks else self

        if target.type not in (PathType.DIRECTORY, PathType.UNKNOWN):
            return True

        if target.type == PathType.DOES_NOT_EXIST:
            if must_exist:
                return False

            return self._semantic_path_type == SemanticPathType.FILE

        return False

    @access_error_handler
    def is_same_file(self, other: os.PathLike[str]) -> bool:
        """Determine if the path is the same file as `other`.

        :param other: The path to compare

        :returns: True if the path is the same file as `other`, False otherwise
        """
        return self._path.samefile(pathlib.Path(other))

    @overload
    @access_error_handler
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
    @access_error_handler
    def open(
        self,
        mode: Literal["rb", "wb", "ab", "r+b", "w+b", "a+b", "xb", "x+b"],
        *,
        buffering: int = -1,
        encoding: None = None,
        errors: None = None,
        newline: None = None,
    ) -> BinaryIO: ...

    @access_error_handler
    def open(
        self,
        mode: str = "r",
        *,
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        """Open the file pointed to by the path, like builtins.open does.

        >>> with Path("path/to/file").open() as f:
        ...     print(f.read())

        These parameters have the same meaning as in :py:meth:`builtins.open`.

        :param mode: The mode ("r", "w", "a", "r+", etc.) to open the file in
        :param buffering: The buffering mode to use (or `None` for default)
        :param encoding: The encoding to use (or `None` for default)
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)

        :returns: A file object pointing to the given path opened in the given mode, etc.
        """
        return self._path.open(mode=mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline)

    @access_error_handler
    def read_text(self, *, encoding: str = "utf-8", errors: str | None = None, newline: str | None = None) -> str:
        """Open the file pointed to in text mode, read its contents, and close the file.

        >>> Path("/path/to/file").write_text("Hello world!")
        >>> Path("/path/to/file").read_text()
        'Hello world!'

        These parameters have the same meaning as in :py:meth:`builtins.open`.

        :param encoding: The encoding to use
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)

        :returns: The contents of the file
        """
        with open(self, mode="rt", encoding=encoding, errors=errors, newline=newline) as f:
            return f.read()

    @access_error_handler
    def read_lines(
        self,
        *,
        encoding: str = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ) -> list[str]:
        """Read the contents of the file, returning a list of the line contents.

        >>> Path("/path/to/file").write_lines(["Hello", "world!"])
        >>> Path("/path/to/file").read_lines()
        ['Hello', 'world!']

        These parameters have the same meaning as in :py:meth:`builtins.open`.

        :param encoding: The encoding to use
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)

        :returns: A list of the lines in the file
        """
        return self.read_text(encoding=encoding, errors=errors, newline=newline).splitlines()

    @access_error_handler
    def read_bytes(self) -> bytes:
        """Open the file pointed to in text mode, read its contents, and close the file.

        >>> Path("/path/to/file").write_bytes(b"Hello world!")
        >>> Path("/path/to/file").read_bytes()
        b'Hello world!'

        :returns: The contents of the file
        """
        with open(self, mode="rb") as f:
            return f.read()

    @access_error_handler
    def write_bytes(self, data: Buffer, *, mode: Literal["w", "a"] = "w") -> int:
        """Open the file pointed to in binary mode, write `data` to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.

        >>> Path("/path/to/file").write_bytes(b"Hello world!")
        12
        >>> Path("/path/to/file").read_bytes()
        b'Hello world!'
        >>> Path("/path/to/file").write_bytes(b"Goodbye world!", mode="a")
        14
        >>> Path("/path/to/file").read_bytes()
        b'Hello world!Goodbye world!'

        :param data: The data to write
        :param mode: The mode to open the file in ("w" for write, "a" for append)

        :returns: The number of bytes written
        """
        with open(self, mode=f"{mode}b") as f:
            return f.write(data)

    @access_error_handler
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

        >>> Path("/path/to/file").write_text("Hello world!")
        12
        >>> Path("/path/to/file").read_text()
        'Hello world!'
        >>> Path("/path/to/file").write_text("Goodbye world!", mode="a")
        14
        >>> Path("/path/to/file").read_text()
        'Hello world!Goodbye world!'

        The other parameters have the same meaning as in :py:meth:`builtins.open`.

        :param data: The data to write
        :param mode: The mode to open the file in ("w" for write, "a" for append)
        :param encoding: The encoding to use (or `None` for default)
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)

        :returns: The number of bytes written
        """
        with open(self, mode=mode, encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    @access_error_handler
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

        >>> Path("/path/to/file").write_lines(["Hello", "world!"])
        >>> Path("/path/to/file").read_lines()
        ['Hello', 'world!']

        The other parameters have the same meaning as in :py:meth:`builtins.open`.

        :param lines: The lines to write
        :param mode: The mode to open the file in ("w" for write, "a" for append)
        :param encoding: The encoding to use
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)
        """
        with open(self, mode=mode, encoding=encoding, errors=errors, newline=newline) as f:
            f.writelines(lines)

    @access_error_handler
    def write_text_atomic(
        self,
        data: str,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> None:
        """Write the given text to this path, ensuring that the operation is performed atomically (as one unit), which
        guarantees that on an error, the previous state of the file will be preserved.

        >>> Path("/path/to/file").write_text_atomic("Hello world!")
        >>> Path("/path/to/file").read_text()
        'Hello world!'

        The other parameters have the same meaning as in :py:meth:`builtins.open`.

        :param data: The data to write
        :param encoding: The encoding to use (or `None` for default)
        :param errors: The error handling to use (or `None` for default)
        :param newline: The newline character to use (or `None` for default)
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

    @access_error_handler
    def __iter__(self) -> Iterator[Self]:
        """Iterate over the children of the directory represented by this path.

        >>> for child in Path("/path/to/directory/"):
        ...     print(child)

        :yields: Direct children of this path

        :raises FileNotFoundError: If this path does not exist
        :raises NotADirectoryError: If this path is not a directory
        :raises OSError: If this path cannot be accessed for, e.g., permissions reasons.
        """
        return self.iterdir()

    @access_error_handler
    def iterdir(self) -> Iterator[Self]:
        """Iterate over the children of the directory represented by this path.

        >>> for child in Path("/path/to/directory/").iterdir():
        ...     print(child)

        :yields: Direct children of this path

        :raises FileNotFoundError: If this path does not exist
        :raises NotADirectoryError: If this path is not a directory
        :raises OSError: If this path cannot be accessed for, e.g., permissions reasons.
        """
        for path in self._path.iterdir():
            semantics = SemanticPathType.DIRECTORY if path.is_dir() else SemanticPathType.FILE
            yield type(self)._from_pathlib_path(path, semantic_path_type=semantics)

    @access_error_handler
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

        Perform copies file-to-file:
        >>> Path("/path/to/source/file").copy("/path/to/destination/file")

        Perform copies file-to-directory (file will be copied into the directory):
        >>> Path("/path/to/source/file").copy("/path/to/destination/directory")

        Perform copies directory-to-directory (recursively):
        >>> Path("/path/to/source/directory").copy("/path/to/destination/directory")

        Perform directory-to-directory copies while ignoring certain files:
        >>> Path("/path/to/source/directory").copy("/path/to/destination/directory", ignore=["*.pyc"])

        .. warning::
            Even with `metadata=True`, some metadata may not me guaranteed to be preserved due to limitations in
            what is exposed by the underlying operating system.

            - On POSIX platforms, this means that file group and group are lost as well as ACLs.
            - On MacOS, the resource fork and other metadata are not used. This means that resources will be lost and
              file type and creator codes will not be correct.
            - On Windows, file owners, ACLs, and alternate data streams are not copied.

        :param to:
            The path (file or directory) to copy this path to.

        :param follow_symlinks:
            Only used when the source (`self`) is a file:

            If True and `self` is a symlink, then `to` will be a copy of the symlink target;
            if False and `self` is a symlink, then `to` will be created as a symlink.

        :param metadata:
            Whether to attempt to copy metadata.

        :param maintain_symlinks:
            Only used when the source (`self`) is a directory:

            If True, symlinks in the source tree are represented as symlinks in the new tree, and the metadata
            is copied as far as the platform allows;
            if False, the contents and metadata of the linked files are copied instead. In addition, if False and the
            symlink is broken, an exception will be added in the list of errors raised in an `Error` exception at the
            end of the copy process.

        :param dirs_exist_ok:
            Only used when the source (`self`) is a directory:

            If False and the destination (`to`) already exists, a FileExistsError will be raised;
            if True, the copying operation will continue if it encounters existing directories and files within the
            `to` tree will be overwritten by corresponding files in the `self` tree.

        :param ignore:
            Only used when the source (`self`) is a directory:

            A list of glob patterns that should be ignored when copying a directory.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If any path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If any errors occur while copying directory-to-directory. In this case, the args attribute will
        be a list of tuples of the form (source, destination, exception), containing information about each error
        that occurs.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy from nonexisting path: {self}")

        copy_function = shutil.copy2 if metadata else shutil.copy

        if self.is_directory():
            if ignore is None:
                ignore = tuple()

            try:
                shutil.copytree(
                    self,
                    to,
                    copy_function=copy_function,
                    symlinks=maintain_symlinks,
                    dirs_exist_ok=dirs_exist_ok,
                    ignore=shutil.ignore_patterns(*ignore),
                )
            except shutil.Error as e:
                raise OSError(f"Error while copying directory {self} -> {to}", *e.args)
        else:
            copy_function(self, to, follow_symlinks=follow_symlinks)

    @access_error_handler
    def copy_permissions(self, to: Self, *, follow_symlinks: bool = True) -> None:
        """Copy the permission bits from self to the other path (`to`). The file contents/owner/group are unaffected.

        .. warning::
            Some platforms do not support copying permissions on symlinks. On such a platform, if
            `follow_symlinks=False` and both `self` and `to` are symlinks, this method will simply do nothing and
            return.

        :param follow_symlinks:
            If False and both `self` and `to` are symlinks, this method will attempt to modify the permissions of the
            `to` symlink itself (rather than the target it points to).

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy permissions for nonexistent path: {self}")

        shutil.copymode(self, to, follow_symlinks=follow_symlinks)

    @access_error_handler
    def copy_stat(self, to: Self, *, follow_symlinks: bool = True) -> None:
        """Copy permission bits, last access time, last modification time, and flags to the target path.
        On Linux, this also copies the extended attributes where possible.
        The file contents, owner, and group are unaffected.

        .. warning::
            Some platforms do not support modifying metadata on symlinks. On such a platform, if
            `follow_symlinks=False` and both `self` and `to` are symlinks, this method will simply do nothing and
            return.

        :param follow_symlinks:
            If False and both `self` and `to` are symlinks, this method will attempt to operate on the symlinks
            themselves (rather than the files they point to).

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot copy stat for nonexistent path: {self}")

        shutil.copystat(self, to, follow_symlinks=follow_symlinks)

    @access_error_handler
    def delete(self, *, recursive: bool = False, strict: bool = True, force: bool = False) -> None:
        """Delete this path (file, symlink, or directory). With `force=False`, raise an error if the path doesn't exist.

        Delete a file (equivalent to `rm $FILE`):
        >>> Path("/path/to/file").delete()

        Delete a directory, but only if it's empty (equivalent to `rmdir $DIRECTORY`):
        >>> Path("/path/to/empty/directory/").delete()

        Delete a directory and all of its children, recursively (equivalent to `rm -r $DIRECTORY`):
        >>> Path("/path/to/directory/").delete(recursive=True)
        >>> Path("/path/to/directory/").delete(force=True)  # even if recursive=False !!

        :param recursive:
            If True and the path is a physical directory, delete the entire directory tree;
            if False and the path is a physical directory, fails if the directory is nonempty unless `force` is True.

        :param force:
            If True, proceed without checking for existence and suppressing FileNotFoundError/OSError on failure,
            equivalent to a best-effort delete.

            `force=True` also allows deleting nonempty directories even when `recursive=False`.

        :param strict:
            Alongside `force=False`, raise FileNotFoundError if the path exists but has the wrong semantic type.
            For example, if `p = Path("path/to/file/")` is a physical file (despite its semantic type as directory),
            then `p.delete(strict=False)` will succeed, but `p.delete(strict=True)` will fail.

        :raises FileNotFoundError: If `force=False` and the path does not exist.
        :raises OSError: If the path cannot be deleted for any reason, e.g., permissions reasons.
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

    @access_error_handler
    def move(self, to: Self, *, metadata: bool = True) -> Self:
        """Recursively move this path to the given destination (`to`), returning the new path.

        Move a file to another file path (possibly overwriting the target):
        >>> Path("/path/to/file").move("/path/to/destination/file")

        Move a directory to another directory path:
        >>> Path("/path/to/directory/").move("/path/to/destination/directory/")

        Move a file to a directory (file is moved into the directory):
        >>> Path("/path/to/file").move("/path/to/directory/")
        >>> Path("/path/to/file").move("/path/to/another/directory/with/clashing/target")
        OSError("Destination path '/path/to/another/directory/with/clashing/target' already exists")

        If `self` is a symlink, then a new symlink pointing to its source will be created at the destination and
        `self` will be removed.

        :param to:
            The path to move this path to.
        :param metadata:
            Only used when the source and destination are on different filesystems.

            If True, copy the file metadata from the source to the destination.

        :returns:
            The new path.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If `self` is a file and `to` is a directory that already contains a file with the same name.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot move nonexistent path: {self}")

        copy_function = shutil.copy2 if metadata else shutil.copy
        try:
            dest = pathlib.Path(shutil.move(self, to, copy_function=copy_function))
        except shutil.Error:
            raise OSError(f"Destination path {str(to).rstrip(os.path.sep)}/{self.name} already exists")

        return type(self)._from_pathlib_path(dest, semantic_path_type=self._semantic_path_type)

    @access_error_handler
    def rename(self, to: str | os.PathLike[str], *, force: bool = True) -> Self:
        """Rename this path to the given name, forcibly overwriting the target with `force=True`.

        The target `to` may be absolute or relative; if relative, it is interpreted
        relative to the current working directory (not the given path).

        It is implemented in terms of `os.rename` and thus only works for local paths.

        >>> Path("/path/to/file").rename("/path/to/destination/file")
        Path("/path/to/destination/file")

        :param to:
            The path to rename this path to.
        :param force:
            If True, overwrite the target if it exists.

        :returns:
            The new path.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot rename nonexistent path: {self}")

        if force:
            return self.replace(to)

        return type(self)._from_pathlib_path(self._path.rename(to), semantic_path_type=self._semantic_path_type)

    @access_error_handler
    def replace(self, to: str | os.PathLike[str]) -> Self:
        """Rename this path to the given name, overwriting the target if it exists.

        The target `to` may be absolute or relative; if relative, it is interpreted
        relative to the current working directory (not the given path).

        >>> Path("/path/to/file").replace("/path/to/destination/file")
        Path("/path/to/destination/file")

        :param to:
            The path to rename this path to.

        :returns:
            The new path.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot replace nonexistent path: {self}")

        return type(self)._from_pathlib_path(self._path.replace(to), semantic_path_type=self._semantic_path_type)

    @access_error_handler
    def disk_usage(self) -> DiskUsage:
        """Return disk usage statistics on the given path, as (total, used, free). Values are given in bytes.
        (Unix) The given path must be mounted.

        :returns:
            Disk usage statistics

        :raises FileNotFoundError: If this path does not exist
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot report disk usage for nonexistent path: {self}")

        return DiskUsage(*shutil.disk_usage(self))

    @access_error_handler
    def chown(
        self,
        *,
        user: int | str | None = None,
        group: int | str | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        """Change owner `user` and/or `group` for the given path. Set `=None` to leave them unchanged.
        `user` and `group` can be system username (str) or uid (int). At least one of them is required.

        The user and group can be given by name:
        >>> Path("/path/to/file").owner()
        'emily'
        >>> Path("/path/to/file").chown(user="alice")
        >>> Path("/path/to/file").owner()
        'alice'

        ...or by ID:
        >>> Path("/path/to/file").group_id()
        1001
        >>> Path("/path/to/file").chown(group=1002)
        >>> Path("/path/to/file").group_id()
        1002

        :param user:
            The user to change the owner to (username or uid) or None to leave the owner unchanged.
        :param group:
            The group to change the group to (username or gid) or None to leave the group unchanged.
        :param follow_symlinks:
            If True and `self` is a symbolic link, change the owner for the target of the link;
            otherwise, change the owner for the link itself.

        :raises FileNotFoundError: If this path does not exist
        :raises ValueError: If both `user` and `group` are None
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If `follow_symlinks=False`, the path is a symbolic link, and the platform does not support
        changing metadata of a symlink.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot change owner/group for nonexistent path: {self}")

        if os.name == "nt":
            raise OSError("chown is not supported on Windows.")

        uid = usergroup.get_uid_of(user)
        gid = usergroup.get_gid_of(group)

        if uid == gid == -1:
            raise ValueError("At least one of `user` and `group` must be specified.")

        os.chown(self, uid, gid, follow_symlinks=follow_symlinks)

    @access_error_handler
    def chmod(self, mode: int, *, follow_symlinks: bool = True) -> None:
        """Change the permissions of the given path.

        >>> Path("/path/to/file").chmod(0o755)
        >>> Path("/path/to/file").mode()
        493
        >>> oct(Path("/path/to/file").mode())
        '0o755'

        :param mode:
            The mode to change the permissions to.
        :param follow_symlinks:
            If True and `self` is a symbolic link, change the permissions for the target of the link;
            otherwise, change the permissions for the link itself.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If `follow_symlinks=False`, the path is a symbolic link, and the platform does not support
        changing metadata of a symlink.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot change permissions for nonexistent path: {self}")

        os.chmod(self, mode, follow_symlinks=follow_symlinks)

    @access_error_handler
    def __contains__(self, other: str | os.PathLike[str]) -> bool:
        """Determine whether the other path is within the subpath of this path.

        >>> Path("/path/to/file") in Path("/path/")
        True
        >>> Path("/path/to/file") in Path("/path/somewhere/else")
        False

        .. note::
            This method is equivalent to :py:meth:`is_relative_to`. This means that it checks the entire subtree
            rooted at `self`, returning True for both immediate children and deeper descendants.

            By contrast, iteration of directories (:py:meth:`__iter__` and :py:meth:`iterdir`) only returns
            immediate children. Thus:

            >>> Path("/path/to/file") in Path("/path/")
            True
            >>> Path("/path/to/file") in list(Path("/path/"))
            False

        :param other:
            The path to check.
        :return:
            True if the other path is within the subpath of this path, False otherwise.
        """
        return type(self)(other).is_relative_to(self, strict=True)

    @access_error_handler
    def _get_relative_depth(self, other: Self) -> int:
        """Returns the number of components in `other` relative to `self`.

        >>> Path("/path/to/file")._get_relative_depth(Path("/path/to/file"))
        0
        >>> Path("/path/to/")._get_relative_depth(Path("/path/to/file"))
        1
        >>> Path("/path/")._get_relative_depth(Path("/path/to/file"))
        2
        >>> Path("/path/to/file")._get_relative_depth(Path("/path/to/somewhere/else/"))
        ValueError("Path '/path/to/somewhere/else/' is not contained within '/path/to/file'.")

        :param other:
            The path to check.
        :return:
            The number of components in `other` relative to `self`.
            In other words, the "depth" of `other` relative to `self`.
        """
        if other not in self:
            raise ValueError(f"Path {other} is not contained within {self}.")

        if self.is_same_file(other):
            # before Python 3.12, self.relative_to(self) was Path("."), which has length 1
            return 0

        return len(other.relative_to(self).parts)

    @access_error_handler
    def walk(
        self, *, top_down: bool = True, on_error: Callable[[OSError], None] | None = None, follow_symlinks: bool = False
    ) -> Iterator[tuple[Self, list[str], list[str]]]:
        """Generate the file names in a directory tree by walking the directory tree.

        For each directory in the tree rooted this path, it yields a 3-tuple (dirpath, dirnames, filenames):
            - dirpath: a Path object currently being walked
            - dirnames: a list of the names of the directories at this path
            - filenames: a list of the names of the non-directory files at this path

        For the file structure:
            /path/to/
            ├── subdir/
            │   ├── subfile1
            │   └── subfile2
            └── file

        >>> list(Path("/path/to/").walk())
        [
            (Path('/path/to/'), ['subdir'], ['file']),
            (Path('/path/to/subdir'), [], ['subfile1', 'subfile2'])
        ]

        If the path is not a directory, no error is raised:
        >>> list(Path("/path/to/file").walk())
        []

        If the path does not exist, no error is raised:
        >>> list(Path("/path/to/does/not/exist").walk())
        []

        :param top_down:
            If True, the triple for a directory is generated before those for any subdirectories. In addition, the
            caller can modify the dirnames and filenames lists, which will affect the contents of the next yielded
            tuple.

            If False, the triple for a directory is generated after the triples for all of its subdirectories.

        :param on_error:
            A callback for error handling. By default, errors are ignored. If `on_error` is not None, it should be
            a callable that takes an :py:exc:`OSError` as its only argument. The callable can handle the error to
            continue the walk or re-raise it to stop the walk. The filename that caused the error is available as
            the `filename` attribute.

        :param follow_symlinks:
            If False (default), the walk does not follow symbolic links and adds them to the filenames list as if they
            were regular files;
            if True, the symlinks will be resolved and will be added to `dirnames`/`filenames` lists as appropriate.

            ..note ::
                `follow_symlinks=True` can lead to infinite recursion if a link points to an ancestor directory.
                This method does not keep track of the methods that have already been checked.

        :yields: a 3-tuple (dirpath: Path, dirnames: list[str], filenames: list[str]) for each directory in the tree

        :raises OSError: If any error occurs while walking the directory tree (e.g., permission errors).
        """
        for root_name, dirnames, filenames in os.walk(str(self), top_down, on_error, followlinks=follow_symlinks):
            yield type(self)(root_name), dirnames, filenames

    @access_error_handler
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
        """Iterate over every item (directory and file) within the given path.

        This method is similar to :py:meth:`pathlib.Path.rglob("*")`.

        For the file structure:
        /path/to/
        ├── subdir/
        │   ├── subfile1
        │   └── subfile2
        ├── logs/
        │   ├── log001.log
        │   ├── log002.log
        │   └── log003.log
        └── file

        >>> list(Path("/path/to/").traverse())
        [
            Path('/path/to/'),
            Path('/path/to/subdir'),
            Path('/path/to/subdir/subfile1'),
            Path('/path/to/subdir/subfile2'),
            Path('/path/to/file')
        ]

        If the path is not a directory, no error is raised:
        >>> list(Path("/path/to/file").traverse())
        [Path('/path/to/file')]

        If the path does not exist, no error is raised:
        >>> list(Path("/path/to/does/not/exist").traverse())
        []

        Use `max_depth` to limit the depth of the traversal:
        >>> list(Path("/path/to/").traverse(max_depth=1))
        [
            Path('/path/to/'),
            Path('/path/to/subdir'),
            Path('/path/to/file')
        ]

        >>> Use `exclude_globs` to exclude certain paths:
        >>> list(Path("/path/to/").traverse(exclude_globs=["*.log"]))
        [
            Path('/path/to/'),
            Path('/path/to/subdir'),
            Path('/path/to/subdir/subfile1'),
            Path('/path/to/subdir/subfile2'),
            Path('/path/to/logs/'),
            Path('/path/to/file')
        ]

        :param top_down:
            If True, the triple for a directory is generated before those for any subdirectories. In addition, the
            caller can modify the dirnames and filenames lists, which will affect the contents of the next yielded
            tuple.

            If False, the triple for a directory is generated after the triples for all of its subdirectories.

        :param on_error:
            A callback for error handling. By default, errors are ignored. If `on_error` is not None, it should be
            a callable that takes an :py:exc:`OSError` as its only argument. The callable can handle the error to
            continue the walk or re-raise it to stop the walk. The filename that caused the error is available as
            the `filename` attribute.

        :param follow_symlinks:
            If False (default), the walk does not follow symbolic links and adds them to the filenames list as if they
            were regular files;
            if True, the symlinks will be resolved and will be added to `dirnames`/`filenames` lists as appropriate.

            ..note ::
                Like :py:meth:`walk`, `follow_symlinks=True` can lead to infinite recursion if a link points to an
                ancestor directory. This method does not keep track of the methods that have already been checked.

        :param show_hidden:
            If True, hidden files are included; if False, all hidden files are skipped.

        :param max_depth:
            The maximum depth of the traversal. If None, there is no limit.

        :param exclude_globs:
            A list of glob patterns to exclude from the traversal.

        :yields: Path objects for each directory and file.

        :raises OSError: If any error occurs while walking the directory tree (e.g., permission errors).
        """
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

    @access_error_handler
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
        """Return an iterator over the paths within the given path that match all of the given conditions.

        This method is like :py:meth:`traverse`, but it allows for additional filtering, like the `find` or `fd`
        commands.

        For the file structure:

        /path/to/
        ├── subdir/
        │   ├── subfile1
        │   └── subfile2
        ├── logs/
        │   ├── log001.log
        │   ├── log002.log
        │   └── log003.log
        └── file

        >>> list(Path("/path/to/").find(r"\.log$"))
        [
            Path('/path/to/logs/log001.log'),
            Path('/path/to/logs/log002.log'),
            Path('/path/to/logs/log003.log')
        ]

        >>> list(Path("/path/to/").find("*.log", glob=True))
        [
            Path('/path/to/logs/'),
            Path('/path/to/logs/log001.log'),
            Path('/path/to/logs/log002.log'),
            Path('/path/to/logs/log003.log')
        ]

        >>> list(Path("/path/to/").find(type=PathType.FILE))
        [
            Path('/path/to/file'),
            Path('/path/to/subdir/subfile1'),
            Path('/path/to/subdir/subfile2'),
            Path('/path/to/logs/log001.log'),
            Path('/path/to/logs/log002.log'),
            Path('/path/to/logs/log003.log')
        ]

        >>> list(Path("/path/to/").find(max_depth=1))
        [
            Path('/path/to/subdir/'),
            Path('/path/to/logs/')
            Path('/path/to/file')
        ]

        :param pattern:
            A string or compiled regular expression to match against the path.

        :param glob:
            If True, `pattern` is interpreted as a glob pattern; if False (default), it is a regular expression.

        :param follow_symlinks:
            If False (default), the walk does not follow symbolic links and adds them to the filenames list as if they
            were regular files;
            if True, the symlinks will be resolved and will be added to `dirnames`/`filenames` lists as appropriate.

            ..note ::
                Like :py:meth:`walk`, `follow_symlinks=True` can lead to infinite recursion if a link points to an
                ancestor directory. This method does not keep track of the methods that have already been checked.

        :param min_depth:
            The minimum depth of the traversal. If None, there is no limit.

        :param max_depth:
            The maximum depth of the traversal. If None, there is no limit.

        :param exclude_globs:
            A list of glob patterns to exclude from the traversal.

        :param type:
            A single PathType or an iterable of PathTypes to limit the results to.

        :param extension:
            A file extension to limit the results to.

        :param show_hidden:
            If True, hidden files are included; if False, all hidden files are skipped.

        :yields: Path objects for each directory and file that match all of the conditions.

        :raises OSError: If any error occurs while walking the directory tree (e.g., permission errors).
        """

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

    @access_error_handler
    def touch(self, *, mode: int = 0o666, exist_ok: bool = True, strict: bool = True) -> None:
        """Create an empty file at this path.

        >>> Path("/path/to/file").touch()
        >>> Path("/path/to/file").exists()
        True
        >>> Path("/path/to/file").touch(exist_ok=True)
        >>> Path("/path/to/file").touch(exist_ok=False)
        FileExistsError: [Errno 17] File exists: '/path/to/file'

        :param mode: The mode to create the file with (default: 0o666)
        :param exist_ok: If True, the file is created if it does not exist; if False, FileExistsError is raised
        :param strict: If True, the path must be semantically a file; if False, semantic type is ignored

        :raises FileExistsError: If the file already exists and `exist_ok` is False
        :raises FileNotFoundError: If any of the parent directories do not exist.
        :raises IsADirectoryError: If `self` is semantically a directory and `strict=True`
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        if strict and self._semantic_path_type == SemanticPathType.DIRECTORY:
            raise IsADirectoryError(f"Cannot `touch` directory: {self}. Use `mkdir` instead.")

        self._path.touch(mode=mode, exist_ok=exist_ok)

    @access_error_handler
    def mkdir(self, *, mode: int = 0o777, parents: bool = False, exist_ok: bool = False, strict: bool = True) -> None:
        """Create a directory at this path.

        >>> Path("/path/to/dir").mkdir()
        >>> Path("/path/to/dir").mkdir(exist_ok=True)
        >>> Path("/path/to/dir").mkdir(exist_ok=False)
        FileExistsError: [Errno 17] File exists: '/path/to/dir'

        Use `parents=True` to create intermediate directories:
        >>> Path("/path/to/deeply/nested/directory/all/the/way/down/here").mkdir(parents=True)

        :param mode: The mode to create the directory with (default: 0o777)
        :param parents: If True, any missing parent directories are created as needed (default: False)
        :param exist_ok: If True, the directory is created if it does not exist; if False, FileExistsError is raised
        :param strict: If True, the path must be semantically a directory; if False, semantic type is ignored

        :raises FileExistsError: If the directory already exists and `exist_ok=False`
        :raises FileNotFoundError: If any of the parent directories do not exist and `parents=False`
        :raises NotADirectoryError: If `self` is semantically a file and `strict=True`
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        if strict and self._semantic_path_type == SemanticPathType.FILE:
            raise NotADirectoryError(f"Cannot `mkdir` file: {self}. Use `touch` instead.")

        self._path.mkdir(mode=mode, parents=parents, exist_ok=exist_ok)

    @access_error_handler
    def symlink_to(self, target: str | os.PathLike[str], *, target_is_directory: bool = False) -> None:
        """Make this path a symbolic link pointing to `target`.

        >>> Path("/path/to/symlink").symlink_to("/path/to/target")
        >>> Path("/path/to/symlink").read_link()
        Path("/path/to/target")

        :param target: The target of the symbolic link
        :param target_is_directory:
            Ignored on non-Windows platforms.

            On Windows, this must be set to True if `target` is a directory and False if it is a file.

        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If :py:meth:`os.symlink` cannot be used on this platform.
        """
        self._path.symlink_to(target, target_is_directory=target_is_directory)

    @access_error_handler
    def hardlink_to(self, target: str | os.PathLike[str]) -> None:
        """Make this path a hard link pointing to `target`.

        >>> Path("/path/to/hardlink").hardlink_to("/path/to/target")

        :raises OSError: If either path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If :py:meth:`os.link` cannot be used on this platform.
        """
        self._path.link_to(target)

    @access_error_handler
    def owner(self, *, follow_symlinks: bool = True) -> str:
        """Return the username of the file owner.

        >>> Path("/bin/sh").user()
        'root'

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the username for the target of the link;
            if False, return the username for the link itself.

        :returns: The user name for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If the user name cannot be determined on this platform.
        """
        if os.name == "nt":
            raise OSError("Owner name cannot be determined on this platform.")

        try:
            import pwd
        except ImportError:
            # collapse the NotImplementedError/pathlib.UnsupportedOperation dichotomy
            raise OSError("Owner name cannot be determined on this platform.")

        return pwd.getpwuid(self.owner_id(follow_symlinks=follow_symlinks)).pw_name

    @access_error_handler
    def owner_id(self, *, follow_symlinks: bool = True) -> int:
        """Return the user ID of the file owner.

        >>> Path("/path/to/file").user_id()
        1000

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the user id for the target of the link;
            if False, return the user id for the link itself.

        :returns: The user ID for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return self.stat(follow_symlinks=follow_symlinks).st_uid

    @access_error_handler
    def group(self, *, follow_symlinks: bool = True) -> str:
        """Return the group name of the file owner.

        >>> Path("/bin/sh").group()
        'root'

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the group name for the target of the link;
            if False, return the group name for the link itself.

        :returns: The group name for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If the group name cannot be determined on this platform.
        """
        if os.name == "nt":
            raise OSError("Group name cannot be determined on this platform.")

        try:
            import grp
        except ImportError:
            # collapse the NotImplementedError/pathlib.UnsupportedOperation dichotomy
            raise OSError("Group name cannot be determined on this platform.")

        return grp.getgrgid(self.group_id(follow_symlinks=follow_symlinks)).gr_name

    @access_error_handler
    def group_id(self, *, follow_symlinks: bool = True) -> int:
        """Return the group ID of the file owner.

        >>> Path("/path/to/file").group_id()
        1001

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the group id for the target of the link;
            if False, return the group id for the link itself.

        :returns: The group ID for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return self.stat(follow_symlinks=follow_symlinks).st_gid

    @access_error_handler
    def mode(self, *, follow_symlinks: bool = True) -> int:
        """Return the numeric octal mode (permissions) of the file.

        >>> Path("/path/to/file/with/mode/0o755").mode()
        493
        >>> oct(Path("/path/to/file/with/mode/0o755").mode())
        '0o755'

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the permission mask for the target of the link;
            if False, return the permission mask for the link itself.

        :returns: The numeric (octal) mode (permissions) for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        mode = self.stat(follow_symlinks=follow_symlinks).st_mode
        return stat.S_IMODE(mode)

    @access_error_handler
    def permission_string(self, *, follow_symlinks: bool = True) -> str:
        """Return the symbolic permission string of the file (e.g., "-rwxr-xr-x").

        >>> Path("/path/to/file/with/mode/0o755").permission_string()
        '-rwxr-xr-x'

        This string also includes the file type character prefix ("-" for files, "d" for directories).

        :returns: The symbolic permission string for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return oct(self.mode(follow_symlinks=follow_symlinks))

    @access_error_handler
    def inode(self, *, follow_symlinks: bool = True) -> int:
        """Return the inode number of the file.

        >>> Path("/path/to/file").inode()
        1238760

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the inode number for the target of the link;
            if False, return the inode number for the link itself.

        :returns: The inode number for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return self.stat(follow_symlinks=follow_symlinks).st_ino

    @access_error_handler
    def device(self, *, follow_symlinks: bool = True) -> int:
        """Return the device number of the file.

        >>> Path("/path/to/file").device()
        35

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the device number for the target of the link;
            if False, return the device number for the link itself.

        :returns: The device number for the given file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return self.stat(follow_symlinks=follow_symlinks).st_dev

    @access_error_handler
    def hardlinks(self, *, follow_symlinks: bool = True) -> int:
        """Return the number of hard links to the file.

        >>> Path("/path/to/file").hardlinks()
        1

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the number of links to the target of the link;
            if False, return the number of links to the link itself.

        :returns: The number of hard links to the file.

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return self.stat(follow_symlinks=follow_symlinks).st_nlink

    @access_error_handler
    def size(
        self,
        *,
        follow_symlinks: bool = True,
        unit: DecimalSizePrefix | BinarySizePrefix = "B",
    ) -> float:
        """Return the size of the file or directory, in the given unit.

        >>> Path("/path/to/file/with/size/41229/bytes").size()
        41229.0
        >>> Path("/path/to/file/with/size/41229/bytes").size(unit="KB")
        41.229
        >>> Path("/path/to/file/with/size/41229/bytes").size(unit="KiB")
        40.26269531

        When `self` is a directory, return the size of the entire tree with this path as the root.

        :param follow_symlinks:
            If True and `self` is a symbolic link, return the size of the target of the link;
            if False, return the size of the link itself.

        :param unit: The unit to return the size in. It must be one of "B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB",
        "YB", or their binary equivalents ("KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB", "RiB", "QiB").

        :returns: The size of the file or directory in the given unit.
        """
        if unit not in SIZE_PREFIX_CONVERSIONS.keys():
            raise ValueError(f"Invalid size unit: {unit}")

        factor = SIZE_PREFIX_CONVERSIONS[unit]

        if self.type == PathType.DIRECTORY:
            total = 0.0
            try:
                for child in self:
                    total += child.size(follow_symlinks=follow_symlinks, unit="B")
            except OSError as e:
                raise OSError(f"Failed to calculate recursive size for directory: {self}. Details: {e}")

            return total / factor

        return self.stat(follow_symlinks=follow_symlinks).st_size / factor

    @access_error_handler
    def accessed_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last access time of the file.

        >>> Path("/path/to/file/accessed/2025-10-13/at/15h14m28s").accessed_time()
        datetime.datetime(2025, 10, 13, 15, 14, 28)

        :returns: The last access time of the file

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_atime)

    @access_error_handler
    def modified_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last modification time of the file.

        >>> Path("/path/to/file/modified/2025-10-13/at/15h14m28s").modified_time()
        datetime.datetime(2025, 10, 13, 15, 14, 28)

        :returns: The last modification time of the file

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        """
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_mtime)

    @access_error_handler
    def metadata_modified_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the last metadata change time of the file.

        >>> Path("/path/to/file/modified/2025-10-13/at/15h14m28s").metadata_modified_time()
        datetime.datetime(2025, 10, 13, 15, 14, 28)

        :returns: The last metadata change time of the file

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.

        """
        return datetime.fromtimestamp(self.stat(follow_symlinks=follow_symlinks).st_ctime)

    @access_error_handler
    def _created_time_windows(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file (Windows implementation)."""
        attr = "st_ctime" if sys.version_info < (3, 12) else "st_birthtime"
        stat_info = self.stat(follow_symlinks=follow_symlinks)

        ts = getattr(stat_info, attr)
        return datetime.fromtimestamp(ts)

    @access_error_handler
    def _created_time_posix(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file (POSIX implementation)."""
        try:
            # st_birthtime is not always available
            # "type ignore" is used because mypy cannot determine whether it exists
            ts = self.stat(follow_symlinks=follow_symlinks).st_birthtime  # type: ignore
        except AttributeError:
            raise OSError("Creation time cannot be determined on this platform.")

        return datetime.fromtimestamp(ts)

    @access_error_handler
    def created_time(self, *, follow_symlinks: bool = True) -> datetime:
        """Return the creation time of the file.

        >>> Path("/path/to/file/created/2025-10-13/at/15h14m28s").created_time()
        datetime.datetime(2025, 10, 13, 15, 14, 28)

        :returns: The creation time of the file

        :raises FileNotFoundError: If this path does not exist
        :raises OSError: If the path cannot be accessed for, e.g., permissions reasons.
        :raises OSError: If the creation time cannot be determined on this platform.
        """

        if os.name == "nt":
            return self._created_time_windows(follow_symlinks=follow_symlinks)

        return self._created_time_posix(follow_symlinks=follow_symlinks)
