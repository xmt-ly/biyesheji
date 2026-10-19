"""使用 SQLite 在线备份接口保存一致性快照，不修改源数据库。"""

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def create_backup(project_root: Path, data_dir: Path | None = None) -> Path:
    root = Path(project_root).resolve()
    data = Path(data_dir or root / "data").resolve()
    if not data.is_relative_to(root):
        raise ValueError("数据目录必须位于当前项目内")
    source = (data / "collaboration.db").resolve()
    if not source.is_relative_to(data):
        raise ValueError("数据库路径超出数据目录")
    if not source.is_file():
        raise FileNotFoundError("数据库不存在，请先初始化或启动系统")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = (root / "work" / "backups" / f"{stamp}-{uuid4().hex[:8]}").resolve()
    if not target.is_relative_to(root):
        raise ValueError("备份目录超出当前项目")
    target.mkdir(parents=True)
    # mode=ro 避免错误路径意外创建空数据库。
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target / "collaboration.db") as snapshot:
            original.backup(snapshot)

    files_count = 0
    source_files = data / "files"
    (target / "files").mkdir()
    if source_files.exists():
        if not source_files.resolve().is_relative_to(data):
            raise ValueError("附件目录超出数据目录")
        for item in source_files.rglob("*"):
            if item.is_symlink() or not item.resolve().is_relative_to(data):
                raise ValueError("附件目录中存在越界链接")
            if item.is_file():
                destination = target / "files" / item.relative_to(source_files)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                files_count += 1

    key = data / "jwt.key"
    if key.exists():
        if key.is_symlink() or not key.resolve().is_relative_to(data):
            raise ValueError("登录凭据文件路径超出数据目录")
        shutil.copy2(key, target / "jwt.key")

    with (target / "collaboration.db").open("rb") as snapshot_file:
        digest = hashlib.file_digest(snapshot_file, "sha256").hexdigest()
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": "collaboration.db",
        "database_sha256": digest,
        "files_count": files_count,
        "contains_login_signing_key": (target / "jwt.key").exists(),
    }
    (target / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def main():
    parser = argparse.ArgumentParser(description="备份数据库、附件及登录签名文件")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    target = create_backup(Path(__file__).resolve().parents[1], args.data_dir)
    print(f"备份已保存：{target}")
    print("备份包含项目数据和登录签名文件，请保存在可信位置。")


if __name__ == "__main__":
    main()
