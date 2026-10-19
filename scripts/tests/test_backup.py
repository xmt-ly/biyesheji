import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


def load_backup():
    path = Path(__file__).parents[1] / "backup.py"
    assert path.exists(), "一致性备份工具尚未实现"
    spec = importlib.util.spec_from_file_location("project_backup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_backup


def make_project(root):
    (root / "data" / "files").mkdir(parents=True)
    with sqlite3.connect(root / "data" / "collaboration.db") as db:
        db.execute("CREATE TABLE records (value TEXT)")
        db.execute("INSERT INTO records VALUES ('original')")
    (root / "data" / "files" / "sample.txt").write_text("演示附件", encoding="utf-8")
    return root


def test_backup_preserves_database_and_attachments(tmp_path):
    create_backup = load_backup()
    root = make_project(tmp_path / "project")
    destination = create_backup(root)
    assert destination.is_relative_to(root / "work" / "backups")
    with sqlite3.connect(destination / "collaboration.db") as db:
        assert db.execute("SELECT value FROM records").fetchall() == [("original",)]
    assert (destination / "files" / "sample.txt").read_text(encoding="utf-8") == "演示附件"
    metadata = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["files_count"] == 1
    assert (root / "data" / "collaboration.db").exists()


def test_missing_database_is_not_created_by_backup(tmp_path):
    create_backup = load_backup()
    root = tmp_path / "project"
    root.mkdir()
    with pytest.raises(FileNotFoundError):
        create_backup(root)
    assert not (root / "data" / "collaboration.db").exists()


def test_each_backup_is_independent_and_old_backup_unchanged(tmp_path):
    create_backup = load_backup()
    root = make_project(tmp_path / "project")
    first = create_backup(root)
    with sqlite3.connect(root / "data" / "collaboration.db") as db:
        db.execute("INSERT INTO records VALUES ('new')")
    second = create_backup(root)
    assert first != second
    with sqlite3.connect(first / "collaboration.db") as db:
        assert db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
    with sqlite3.connect(second / "collaboration.db") as db:
        assert db.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2
