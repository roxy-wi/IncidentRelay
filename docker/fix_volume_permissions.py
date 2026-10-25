"""Securely reconcile Docker named-volume ownership before dropping root.

This script is only called by the root entrypoint. It never traverses symbolic
links or other filesystems, and does not change ownership on already-correct
files. Kubernetes pods run directly as a non-root UID and skip this step.
"""

import os
import stat

RUNTIME_UID = 10001
RUNTIME_GID = 10001
VOLUME_DIRS = ("/var/lib/incidentrelay", "/var/log/incidentrelay")


def fix_volume_ownership(path: str, *, uid: int, gid: int) -> int:
    """Fix ordinary files and directories, rooted at a no-follow directory fd.

    Every ownership change uses a directory/file descriptor so symlinks cannot
    redirect the operation outside the trusted volume. Other-device mounts and
    symlinks are neither modified nor traversed.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(path, flags)
    changed = 0
    try:
        root_device = os.fstat(root_fd).st_dev
        for _, dirs, files, current_fd in os.fwalk(
            ".", topdown=True, follow_symlinks=False, dir_fd=root_fd
        ):
            current = os.fstat(current_fd)
            if current.st_dev != root_device:
                dirs[:] = []
                continue

            if (current.st_uid, current.st_gid) != (uid, gid):
                os.fchown(current_fd, uid, gid)
                changed += 1

            for name in dirs[:]:
                try:
                    entry = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                except FileNotFoundError:
                    # Another worker removed an ephemeral directory during scan.
                    dirs.remove(name)
                    continue
                if not stat.S_ISDIR(entry.st_mode) or entry.st_dev != root_device:
                    dirs.remove(name)

            for name in files:
                try:
                    entry = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(entry.st_mode) or entry.st_dev != root_device:
                    continue
                if (entry.st_uid, entry.st_gid) != (uid, gid):
                    try:
                        os.chown(name, uid, gid, dir_fd=current_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        # SQLite and metric files can disappear during repair.
                        continue
                    changed += 1
    finally:
        os.close(root_fd)
    return changed


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Volume ownership repair requires root")
    for path in VOLUME_DIRS:
        try:
            fix_volume_ownership(path, uid=RUNTIME_UID, gid=RUNTIME_GID)
        except OSError as exc:
            raise SystemExit(
                f"Cannot prepare {path} for UID/GID {RUNTIME_UID}:{RUNTIME_GID}: {exc}. "
                "Check volume ownership and filesystem permissions."
            ) from exc


if __name__ == "__main__":
    main()
