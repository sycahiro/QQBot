"""Fixed managed paths only; never follow Windows junctions or directory links."""

import re
import stat
from pathlib import Path

ACCOUNT = re.compile(r"[1-9][0-9]{4,11}\Z")
LOG_SESSION = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.\d+-\d+\Z")
LOG_FILES = {"desktop.log", "frontend.log", "launcher.log"}
INDEX_FILES = {
    name + suffix
    for name in ("messages.db", "media.db", "reactions.db")
    for suffix in ("", "-wal", "-shm", "-journal")
}


def managed(path, root):
    """Check every component, including root, without resolving through a link."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root):
        raise ValueError("存储路径超出管理范围")
    if root.resolve() != root:
        raise ValueError("存储根目录包含链接，未执行操作")
    parts = [root]
    for name in path.relative_to(root).parts:
        parts.append(parts[-1] / name)
    for part in parts:
        if part.is_symlink() or part.is_junction():
            raise ValueError("存储路径包含链接，未执行操作")
        try:
            mode = part.lstat()
        except FileNotFoundError:
            continue
        if getattr(mode, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError("存储路径包含重解析点，未执行操作")
    return path


def file_size(path, root):
    path = managed(path, root)
    try:
        item = path.lstat()
    except FileNotFoundError:
        return 0
    if not stat.S_ISREG(item.st_mode):
        raise ValueError("存储文件类型异常")
    return item.st_size


def children(path, root):
    path = managed(path, root)
    if not path.exists():
        return []
    return sorted(path.iterdir())


def tree_files(path, root, *, limit=10000):
    pending, files = [managed(path, root)], []
    visited = 0
    while pending:
        directory = pending.pop()
        for entry in children(directory, root):
            visited += 1
            if visited > limit:
                raise ValueError("临时文件过多，请分批整理后重试")
            managed(entry, root)
            if entry.is_dir():
                pending.append(entry)
            elif entry.is_file():
                files.append(entry)
            else:
                raise ValueError("临时文件类型异常")
    return files


def remove_files(files, root):
    deleted, freed, failures = 0, 0, []
    # Validate the complete fixed selection before deleting its first item.
    for file in files:
        file_size(file, root)
    for file in files:
        try:
            size = file_size(file, root)
            if not file.exists():
                continue
            file.unlink()
            deleted += 1
            freed += size
        except OSError:
            failures.append("文件被占用或无法删除")
    return {"deletedFiles": deleted, "freedBytes": freed, "failures": failures}
