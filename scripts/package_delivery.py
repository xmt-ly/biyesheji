"""仅用标准库生成可复核、无本机凭据的本地交付 ZIP。"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile


SOURCE_ROOTS = ("README.md", ".env.example", "backend", "frontend", "docs", "scripts", "experiments")
RESULT_ROOTS = (("experiments", "results"), ("experiments", "reliability_v3", "results"),
                ("experiments", "reliability_followup", "results"))
EXCLUDED_PARTS = frozenset({
    "node_modules", "__pycache__", ".git", "data", "work", "backups",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".npm-cache",
    ".venv", "venv", ".tox", ".coverage", "htmlcov", "cache", "caches",
})
SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".jks", ".keystore", ".db", ".sqlite", ".sqlite3",
                   ".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm", ".sqlite-journal",
                   ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".pyc", ".pyo")
SECRET_NAMES = frozenset({".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa"})
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _reject_link(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"拒绝符号链接或 Windows 重解析点：{path}")


def _inside(root, value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError(f"路径不能含 ..：{value}")
    path = path if path.is_absolute() else root / path
    if not path.is_relative_to(root):
        raise ValueError(f"路径超出项目目录：{value}")
    for ancestor in [path, *path.parents]:
        _reject_link(ancestor)
        if ancestor == root:
            break
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"解析后路径超出项目目录：{value}")
    return path


def _excluded(relative, *, evidence=False):
    if relative.as_posix() == ".env.example":
        return False
    parts = [part.lower() for part in relative.parts]
    if evidence:
        parts = parts[1:]  # 仅显式选择的 work 子路径可进入。
    if any(part in EXCLUDED_PARTS or part.startswith(".env") for part in parts):
        return True
    name = parts[-1]
    return (name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES)
            or name.startswith(("credentials.", "credential.", "secrets.", "secret.", "tokens.")))


def _collect(root, path, selected, *, evidence=False, result=False):
    relative = path.relative_to(root)
    if _excluded(relative, evidence=evidence):
        return
    result_parts = tuple(part.casefold() for part in relative.parts)
    if not result and any(result_parts[:len(parts)] == parts for parts in RESULT_ROOTS):
        return
    _inside(root, path)
    if path.is_dir():
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            _collect(root, child, selected, evidence=evidence, result=result)
    elif path.is_file():
        selected[relative.as_posix()] = path
    elif path.exists():
        raise ValueError(f"只支持普通文件或目录：{relative}")


def _read(root, path):
    _inside(root, path)
    with path.open("rb") as source:
        return source.read()


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def create_delivery(root, output="work/delivery/course-collaboration.zip", *, result_dirs=(), evidence=()):
    """打包固定白名单及显式证据，不导入应用、不载入环境文件。已有输出拒绝覆盖。"""
    root = Path(root).absolute()
    for ancestor in [root, *root.parents]:
        _reject_link(ancestor)
    if not root.is_dir():
        raise ValueError("项目根目录不存在")
    destination = _inside(root, output)
    relative_output = destination.relative_to(root)
    if relative_output.parts[:2] != ("work", "delivery") or len(relative_output.parts) < 3:
        raise ValueError("输出只能写入项目 work/delivery/ 内")
    if destination.suffix.lower() != ".zip":
        raise ValueError("输出文件必须使用 .zip 后缀")
    if destination.exists():
        raise FileExistsError(f"拒绝覆盖已有交付包：{destination}")

    selected = {}
    source_names = {name.casefold() for name in SOURCE_ROOTS}
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name.casefold() in source_names:
            path = _inside(root, entry)
            _collect(root, path, selected)

    selected_results = []
    for value in result_dirs:
        path = _inside(root, value)
        relative = path.relative_to(root)
        if tuple(part.casefold() for part in relative.parts[:-1]) not in RESULT_ROOTS:
            raise ValueError("真实结果必须明确指定 experiments/results/、experiments/reliability_v3/results/ "
                             "或 experiments/reliability_followup/results/ 下的单个运行目录")
        if _excluded(relative) or not path.is_dir():
            raise ValueError("真实结果目录不存在或被排除")
        manifest_path = _inside(root, path / "manifest.json")
        try:
            result_manifest = json.loads(_read(root, manifest_path))
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取真实结果清单：{relative}") from exc
        if not isinstance(result_manifest, dict) or result_manifest.get("run_mode") != "live":
            raise ValueError("拒绝把 dry-run、fixture 或无真实运行标记的目录作为实验结果")
        # 只验证来源标记；部分结果与失败记录按原样保存，绝不改写为完整实验。
        _collect(root, path, selected, result=True)
        selected_results.append(relative.as_posix())

    selected_evidence = []
    for value in evidence:
        path = _inside(root, value)
        relative = path.relative_to(root)
        if (not relative.parts or relative.parts[0] != "work" or len(relative.parts) < 2
                or relative.parts[:2] == ("work", "delivery") or _excluded(relative, evidence=True)):
            raise ValueError("证据须为 work/ 内明确的非敏感报告文件或记录子树，不能选择整个 work 或交付输出")
        if not path.exists():
            raise ValueError(f"证据路径不存在：{relative}")
        _collect(root, path, selected, evidence=True)
        selected_evidence.append(relative.as_posix())

    payloads = [(name, _read(root, selected[name])) for name in sorted(selected)]
    manifest = {
        "schema_version": 1,
        "result_directories": sorted(set(selected_results)),
        "evidence_paths": sorted(set(selected_evidence)),
        "files": [{"path": name, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                  for name, payload in payloads],
    }
    payloads.append(("manifest.json", _json_bytes(manifest)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    _inside(root, destination)
    # xb 保证即使检查之后出现同名文件也不会覆盖。
    with destination.open("xb") as archive_file:
        try:
            with zipfile.ZipFile(archive_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, payload in sorted(payloads):
                    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, payload, compresslevel=9)
        except BaseException:
            archive_file.close()
            destination.unlink(missing_ok=True)
            raise
    return destination


def _safe_archive_name(name):
    path = PurePosixPath(name)
    return (bool(name) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and ":" not in name and path.as_posix() == name)


def verify_delivery(path):
    """离线核对归档文件集合、字节数与 SHA-256；不解压或执行包内文件。"""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if (len(names) != len(set(names)) or "manifest.json" not in names
                or any(not _safe_archive_name(name) for name in names)
                or any(item.create_system == 3 and stat.S_IFMT(item.external_attr >> 16) not in (0, stat.S_IFREG)
                       for item in infos)):
            raise ValueError("归档含重复、越界、链接、目录或缺少清单")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            rows = manifest["files"]
            expected = {row["path"] for row in rows}
            if manifest.get("schema_version") != 1 or len(expected) != len(rows) or "manifest.json" in expected:
                raise ValueError("清单格式无效")
            if expected != set(names) - {"manifest.json"}:
                raise ValueError("归档文件集合与清单不一致")
            for row in rows:
                payload = archive.read(row["path"])
                if len(payload) != row["size"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
                    raise ValueError(f"文件 SHA-256 或字节数校验失败：{row['path']}")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("归档清单格式无效") from exc
    return {"archive": str(path.absolute()), "files_count": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="项目根目录")
    parser.add_argument("--output", default="work/delivery/course-collaboration.zip", help="仅允许 work/delivery/ 内新 ZIP")
    parser.add_argument("--results-dir", action="append", default=[], help="显式真实结果运行目录，可重复；默认不收集任何结果")
    parser.add_argument("--evidence", action="append", default=[], help="work 内报告文件或记录子树，可重复；不选择整个 work")
    parser.add_argument("--verify", type=Path, help="仅离线核对指定 ZIP，不生成或解压文件")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            report = verify_delivery(args.verify)
        else:
            destination = create_delivery(args.root, args.output, result_dirs=args.results_dir, evidence=args.evidence)
            report = verify_delivery(destination)
        print(json.dumps(report, ensure_ascii=True))
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f"交付失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
