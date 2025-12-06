# fluidpath

A high-level wrapper for operating on filesystem paths, providing a modern, cohesive API that aims to consolidate functionality from other filesystem modules (e.g., `shutil`) and eliminate the need for low-level semantics (such as the difference between `shutil.copy` and `shutil.copy2`).

## Why `fluidpath` over `pathlib`?

`fluidpath` is designed to be a high-level, modern way of interfacing with the file-system. I've seen `pathlib` marketed as that, but the latter is bound in a lot of ways to the C calls underpinning the `os` and `os.path` modules and required the separate imports of `os`/`os.path`/`shutil` to have what I consider to be basic functionality, despite `pathlib` being introduced in 3.4 (2014). `fluidpath` also aims to backport new `pathlib` functionality to older versions of Python.

`fluidpath` is, in some cases, an opinionated library, and there are some intentional deviations from the `pathlib` functionality. It is not designed purely as a one-to-one, drop-in replacement, though it aims to not drop any functionality. See the below section for notes about incompatibilities.

### copying

`pathlib.Path` couldn't copy files until 3.14 (2025), requiring the use of `shutil`. But this requires the user to differentiate between `shutil.copyfile`, `.copy`, `.copy2`, and `.copytree`.

```python
# pathlib: uses three different methods in a *different* stdlib module
srcfile = pathlib.Path("/path/to/source/file")
srcdir = pathlib.Path("/path/to/source/dir/")

dstfile = pathlib.Path("/path/to/dst/file")
dstdir = pathlib.Path("/path/to/dst/dir/")

shutil.copy2(srcfile, dstfile)                  # metadata copied: yes ✓
shutil.copy(srcfile, dstfile)                   # metadata copied: no  ✕
shutil.copytree(srcdir, dstdir)                 # metadata copied: yes ✓
shutil.copytree(srcdir, dstdir, shutil.copy)    # metadata copied: no  ✕

# fluidpath
srcfile = fluidpath.Path("/path/to/source/file")
srcdir = fluidpath.Path("/path/to/source/dir/")

dstfile = fluidpath.Path("/path/to/dst/file")
dstdir = fluidpath.Path("/path/to/dst/dir/")


srcfile.copy(to=dstfile)                        # uses shutil.copy2 by default
srcfile.copy(to=dstfile, metadata=False)        # uses shutil.copy
srcdir.copy(to=dstdir)                          # uses shutil.copytree
srcdir.copy(to=dstdir, metadata=False)
```

### deleting

Similarly, there's no unified delete mechanism, requiring the use of `Path.unlink`, `Path.rmdir`, or `shutil.rmtree`.

```python
# pathlib
pathlib.Path("/path/to/file").unlink()
pathlib.Path("/path/to/empty-dir/").rmdir()
shutil.rmtree(pathlib.Path("/path/to/dir/"))

# fluidpath
fluidpath.Path("/path/to/file").delete()
fluidpath.Path("/path/to/empty-dir/").delete()
fluidpath.Path("/path/to/dir/").delete(recursive=True)
```

### `write_text(..., mode="a")`

I like `pathlib.Path.write_text` in a lot of cases since I'm usually operating with a Path object and this saves the hassle of `with open(...)`. But `pathlib.Path.write_text` can't append text to an existing file.

```python
# pathlib
path = pathlib.Path("/path/to/file.txt")
path.write_text(path.read_text() + "some more content")  # incurs two opens

# fluidpath
path = fluidpath.Path("/path/to/file.txt")
path.write_text("some more content", mode="a")
```

### `PathType` enum

`pathlib` requires checking `stat` results and/or multiple `is_*` methods to determine what type a file actually is, such as distinguishing between regular files and symlinks. In addition, per the `pathlib.Path.is_file` documentation, for example, *"False will be returned if the path is invalid, inaccessible or missing, or if it points to something other than a regular file. Use Path.stat() to distinguish between those cases."*

`fluidpath` provides a `PathType` enum to unambiguously encode the type that a file is (`PathType.REGULAR_FILE`, `PathType.SYMLINK`, `PathType.DIRECTORY`, etc.). `fluidpath.Path` exposes this via its `.type` property: `Path("path/to/symlink").type == PathType.SYMLINK` but also provides `is_*` methods as well for convenience.

The full list of members is `REGULAR_FILE`, `DIRECTORY`, `SYMLINK`, `PIPE`, `CHAR_DEVICE`, `BLOCK_DEVICE`, `SOCKET`, `UNKNOWN` (as a fallback if `stat.S_IS*` all return False), and `DOES_NOT_EXIST`.


### additional features

- `Path.find` provides an `fd`-like method of advanced filesystem searching. It consolates many filtering needs (regex/glob searching, min depth, max depth, type, hidden files, exclusion globs) into a single top-level method, bypassing complex `path.walk` manipulation.
- `Path.traverse` is a better version of `pathlib.Path.iterdir` (or `pathlib.Path.rglob("*")`) that returns an iterator over all files in the directory and its children, except that it also provides additional filters (suppressing hidden files, max depth, and exclusion globs) as desired.

## Installation

`fluidpath` can be easily installed for any **Python 3.10+** by any package manager:

```bash
# using pip
pip install fluidpath

# using uv
uv add fluidpath
```

This is a light package, with its only external dependency being `typing_extensions` (Python 3.10), with no external dependencies for Python 3.11+.

## Documentation

### Main incompatibilities with `pathlib.Path`

| **Method**                                       	| **Different Behaviour**                                                                                                                                                                                        	| **In order to use the `pathlib.Path` behaviour...**                               	|
|--------------------------------------------------	|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------	|-----------------------------------------------------------------------------------	|
| `Path.match`                                     	| uses regular expressions for matches, not glob patterns                                                                                                                                                        	| use `Path.glob_match`                                                             	|
| `Path.lstat`                                     	| is intentionally omitted                                                                                                                                                                                       	| use `Path.stat(follow_symlinks=False)`                                            	|
| `Path.open`, `Path.read_text`, `Path.write_text` 	| take their additional arguments (`encoding`, `errors`, `newline`) as keyword-only                                                                                                                              	| ---                                                                               	|
| `Path.rename`                                    	| overwrites the target by default (behaving like `pathlib.Path.replace`)                                                                                                                                        	| use `Path.rename(force=False)`                                                    	|
| `Path.is_directory`                              	| when the path does not exist, behaves semantically: `Path("does/not/exist/").is_directory()` returns `True` because it has a trailing slash (`touch does/not/exist/` would fail on the command line)           	| use `Path.is_directory(must_exist=True)` or use `Path.type == PathType.DIRECTORY` 	|
| `Path.is_file`                                   	| when the path does not exist, behaves semantically: `Path("does/not/exist").is_file()` returns `True` because it does not have a trailing slash (`touch does/not/exist` would succeed on the command line)     	| use `Path.is_regular_file` or use `Path.type == PathType.REGULAR_FILE`            	|
| `Path.is_file`                                   	| does not distinguish between different types of files (e.g., regular files and symlinks both return `True`) because, as its name suggests, it is a broad check for a non-directory path (symlinks *are* files) 	| use `Path.is_regular_file` or use `Path.type == PathType.REGULAR_FILE`    

In addition, some methods are renamed:

| `fluidpath.Path`        	| `pathlib.Path`    	|
|-------------------------	|-------------------	|
| `Path.expand_user`      	| `Path.expanduser` 	|
| `Path.read_link`        	| `Path.readlink`   	|
| `Path.join_path`        	| `Path.joinpath`   	|
| `Path.is_directory`     	| `Path.is_dir`     	|
| `Path.is_mount_point`   	| `Path.is_mount`   	|
| `Path.is_same_file`     	| `Path.samefile`   	|

### Backporting functionality from `pathlib`

- `Path.suffix`,  `Path.suffixes`, and `Path.with_suffix` use the 3.14 `pathlib` behaviour of allowing `Path("path/to/file.").suffix == ["."]`.
- `Path.exists`, `Path.is_directory`, `Path.is_file`, `Path.copy`, `Path.copy_permissions`, `Path.copy_stat`, `Path.chown`, `Path.chmod`, `Path.get_owner`, and `Path.get_group` all support the `follow_symlinks` parameter (as well as `Path.stat`)
- `Path.match` (and its new sister method `Path.glob_match`) support the kw-only `case_sensitive` parameter.

### Additional features

#### API cohesion, consolidation, and convenience

- `Path.copy` and `Path.delete` exist as unified copy and delete mechanisms, respectively, removing the need to use `shutil.copyfile`/`shutil.copy`/`shutil.copy2`/`shutil.copytree` and `Path.unlink`/`Path.rmdir`/`shutil.rmtree`
- `Path.move` is added, granting the same cross-fs capabilities as `shutil.move` (which it uses under the hood).
- `PathType` is an enum for concretely specifying the type of a file (see the above section).
- `Path.chown` is added, aliasing `shutil.chown`, and also supports the `follow_symlinks` parameter.
- `Path.copy_permissions` and `Path.copy_stat` are added, aliasing `shutil.copymode` and `shutil.copystat`, respectively.
- `Path.relative_to` and `Path.is_relative_to` support kw-only `strict: bool = False` (which is `pathlib.Path`'s behaviour). When `strict=True`, the paths are resolved and access the filesystem.
- `Path.is_reserved` exists and returns `True` when the path is reserved on the current platform (always `False` on Unix). This method existed in `pathlib.Path` but was deprecated in Python 3.13 in favour of `os.path.isreserved`.
- `Path` supports `__iter__`, making it iterable (when the path is a directory). `for file in path: ...` is equivalent to `for file in path.iterdir(): ...`.
- `Path` supports `__contains__`. `x in path` is equivalent to `x.is_relative_to(path, strict=True)`.

#### Advanced traversal and searching

- `Path.match` gives functionality for regex-based pattern matching instead of only glob-based matching. (For glob matches, use `Path.glob_match`.)
- `Path.traverse` is added, behaving like `pathlib.Path.rglob("*")`, but with additional conditions: `show_hidden: bool = True` (allows suppression of hidden files), `max_depth: int | None = None` (allows the traversal to only go down a certain number of layers), `exclude_globs: Iterable[str] | None = None` (allows for certain types of files (e.g., `exclude_globs=["*.pyc"]`) to be suppressed).
- `Path.find` is added, giving access to an `fd`-like mechanism for filtering files. It supports both regex (default) and glob (via `glob=True`) patterns, specifying `min_depth` and `max_depth`, `exclude_globs`, specifying `type` (using `PathType`), and `extension`.


#### I/O Enhancements

- `Path.write_text` now supports both `"w"` (default) and `"a"` modes, allowing for writing to a file without clearing it.
- `Path.read_lines` and `Path.write_lines` are added, mimicking the `readlines` and `writelines` methods for file descriptors.

- `Path.write_text_atomic` ensures an atomic write the the file, ensuring that if an error occurs, the file will remain as it was before the write process began, promoting data integrity when partial writes must be avoided.
