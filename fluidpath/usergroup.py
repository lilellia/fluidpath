def get_uid_of(user: int | str | None) -> int:
    """Return the user ID of the given user.

    Raises KeyError if the user does not exist.
    """
    if user is None:
        return -1

    if isinstance(user, str):
        try:
            import pwd
        except ImportError:
            raise OSError("Cannot get user ID with string username on this platform.")

        # raises KeyError if `user` cannot be found
        return pwd.getpwnam(user).pw_uid

    return user


def get_gid_of(group: int | str | None) -> int:
    """Return the group ID of the given group.

    Raises KeyError if the group does not exist.
    """
    if group is None:
        return -1

    if isinstance(group, str):
        try:
            import grp
        except ImportError:
            raise OSError("Cannot get group ID with string group name on this platform.")

        # raises KeyError if `group` cannot be found
        return grp.getgrnam(group).gr_gid

    return group
