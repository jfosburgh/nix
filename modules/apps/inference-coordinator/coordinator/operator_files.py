"""Bounded read-only root/operator files, separate from secret credential loading."""
import os
import stat

from .supervision import SupervisionError, _parts


def read_operator_file(path, *, limit=262144, owner=0):
    directory = descriptor = None
    try:
        parts = _parts(path)
        if not parts or type(owner) is not int or owner < 0 or type(limit) is not int or not 0 < limit <= 1048576:
            raise ValueError('policy')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open('/', flags)
        for part in parts[:-1]:
            info = os.fstat(directory)
            if info.st_uid not in (0, owner) or (info.st_mode & 0o022 and not (
                    info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
                raise ValueError('directory')
            next_fd = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        info = os.fstat(directory)
        if info.st_uid not in (0, owner) or (info.st_mode & 0o022 and not (
                info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
            raise ValueError('directory')
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=directory)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner or before.st_mode & 0o022
                or not 0 < before.st_size <= limit):
            raise ValueError('file')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(descriptor)
        current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if (len(data) != before.st_size or any(getattr(before, k) != getattr(after, k)
                or getattr(before, k) != getattr(current, k) for k in fields)):
            raise ValueError('changed')
        return bytes(data)
    except (OSError, ValueError, TypeError):
        raise SupervisionError('Operator file unavailable or unsafe') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)
