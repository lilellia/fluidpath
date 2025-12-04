from collections.abc import Buffer, Callable, Iterable, Iterator
from enum import auto, Enum
import fnmatch
import inspect
import os
import pathlib
import re
import shutil
import stat
from tempfile import NamedTemporaryFile
from typing import cast, Literal, ParamSpec, Self, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def override(superclass: type) -> Callable[[Callable[P, R]], Callable[P, R]]:
    if not inspect.isclass(superclass):
        raise TypeError(f"argument to @override(...) must be a class, not {superclass!r}")

    def wrapper(method: Callable[P, R]) -> Callable[P, R]:
        if not inspect.isfunction(method):
            raise TypeError(f"@override(...) must decorate a function, not {method!r}")

        name = method.__name__
        if not hasattr(superclass, name):
            raise TypeError(f"{superclass!r} does not define {name!r}. Did you make a typo in the method name?")

        return method

    return wrapper


class PathType(Enum):
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


class Path(pathlib.Path):
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

        if self.is_dir():
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

    def delete(self, *, recursive: bool = False, ignore_errors: bool = False):
        """Delete this path.

        If this path is a directory and `recursive = False`, then this will fail if the directory is nonempty.
        If this path is a directory and `recursive = True`, then the entire tree (rooted at this path) will be deleted.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot delete nonexistent path: {self}")

        if self.is_dir():
            if recursive:
                shutil.rmtree(self, ignore_errors=ignore_errors)
            else:
                self.rmdir()
        else:
            # delete file
            self.unlink()

    def move(self, to: Self, *, metadata: bool = True) -> None:
        """Recursively move this path to the given destination (`to`).
        If `to` is an existing directory, the source is placed inside it.
        If `to` exists but is not a directory, then it may be overwritten.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot move nonexistent path: {self}")

        copy_function = shutil.copy2 if metadata else shutil.copy
        shutil.move(self, to, copy_function=copy_function)

    def disk_usage(self) -> shutil._ntuple_diskusage:
        """Return disk usage statistics on the given path, as (total, used, free). Values are given in bytes.
        (Unix) The given path must be mounted.
        """
        if not self.exists(follow_symlinks=False):
            raise FileNotFoundError(f"Cannot report disk usage for nonexistent path: {self}")

        return shutil.disk_usage(self)

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
        match user, group:
            case None, None:
                raise ValueError("At least one of `user` and `group` must be specified.")
            case user, None:
                user = cast(int | str, user)
                shutil.chown(self, user=user, follow_symlinks=follow_symlinks)
            case None, group:
                group = cast(int | str, group)
                shutil.chown(self, group=group, follow_symlinks=follow_symlinks)
            case user, group:
                user = cast(int | str, user)
                group = cast(int | str, group)
                shutil.chown(self, user=user, group=group, follow_symlinks=follow_symlinks)

    def read_lines(
        self,
        encoding: str = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ) -> list[str]:
        """Read the contents of the file, returning a list of the line contents."""
        return self.read_text(encoding=encoding, errors=errors, newline=newline).splitlines()

    def write_bytes(self, data: Buffer, *, mode: Literal["w", "a"] = "w") -> int:
        """Open the file pointed to in binary mode, write `data` to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.
        """
        with open(self, mode=f"{mode}b") as f:
            return f.write(data)

    @override(pathlib.Path)
    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        *,
        mode: Literal["w", "a"] = "w",
    ) -> int:
        """Open the file pointed to in text mode, write `data` to it, and close the file.
        If `mode = "w"`, an existing file of the same name is overwritten; if `mode = "a"`, data is written to the end.
        """
        with open(self, mode=mode, encoding=encoding, errors=errors, newline=newline) as f:
            return f.write(data)

    def write_lines(
        self,
        lines: Iterable[str],
        mode: Literal["w", "a"] = "w",
        encoding: str = "utf-8",
        errors: str | None = None,
        newline: str | None = None,
    ):
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
    ):
        """Write the given text to this path, ensuring that the operation is performed atomically (as one unit), which
        guarantees that on an error, the previous state of the file will be preserved.
        """
        with NamedTemporaryFile(
            "w",
            encoding=encoding,
            errors=errors,
            newline=newline,
            delete=False,
            dir=self.parent,
        ) as f:
            f.write(data)

        temp_path = self.__class__(f.name)
        try:
            temp_path.replace(self)
        except Exception:
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise

    @property
    def type(self) -> PathType:
        """Return the type of the given path: e.g, REGULAR_FILE or DIRECTORY."""
        if not self.exists(follow_symlinks=False):
            return PathType.DOES_NOT_EXIST

        return identify_st_mode(self.stat().st_mode)

    @override(pathlib.Path)
    def is_dir(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        if self.exists(follow_symlinks=follow_symlinks):
            return super().is_dir(follow_symlinks=follow_symlinks)

        if must_exist:
            return False

        return str(self).endswith("/")

    @override(pathlib.Path)
    def is_file(self, *, follow_symlinks: bool = True, must_exist: bool = False) -> bool:
        if self.exists(follow_symlinks=follow_symlinks):
            return super().is_file(follow_symlinks=follow_symlinks)

        if must_exist:
            return False

        return not str(self).endswith("/")

    def __contains__(self, other: Self) -> bool:
        """Determine whether the other path is within the subpath of this path."""
        return other.is_relative_to(self)

    def _get_relative_depth(self, other: Self) -> int:
        """Returns the number of components in `other` relative to `self`."""
        if other not in self:
            raise ValueError(f"Path {other} is not contained within {self}.")

        if self.samefile(other):
            # before Python 3.12, self.relative_to(self) was Path("."), which has length 1
            return 0

        return len(other.relative_to(self).parts)

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
            root = self.__class__(root_name)

            if exclude_patterns:
                base = self.__class__(".") if self == root else root.relative_to(self)
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
        pattern: str | re.Pattern = "",
        *,
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

        pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        allowed_types = get_allowed_types()

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
