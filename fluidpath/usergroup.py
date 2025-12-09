def get_uid_of(user: int | str | None) -> int:
    """Return the user ID of the given user.

    :param user: The uid or username of the user. If None, return -1.
    :returns: The user ID of the given user.
    :raises OSError: If `user` is a string and the string --> uid mapping is not available on this platform.
    :raises KeyError: If `user` is a string and the username is not a valid user on this system.
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

    :param group: The gid or name of the user. If None, return -1.
    :returns: The group ID of the given group.
    :raises OSError: If `group` is a string and the string --> gid mapping is not available on this platform.
    :raises KeyError: If `group` is a string and the group name is not a valid group on this system.
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
