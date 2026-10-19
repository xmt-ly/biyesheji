"""交付工具的离线路径与归档边界测试；临时结果仅为测试样例。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).parents[1] / "package_delivery.py"


def load_package():
    assert SCRIPT.exists(), "无凭据交付打包工具尚未实现"
    spec = importlib.util.spec_from_file_location("delivery_package", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        for name, content in {
            "README.md": "课程项目交付\n",
            ".env.example": "LLM_API_KEY=\n",
            "backend/app/main.py": "# 后端源码\n",
            "frontend/src/App.vue": "<template>课程协作</template>\n",
            "frontend/package-lock.json": "{}\n",
            "frontend/dist/index.html": "<html>当前生产构建</html>\n",
            "docs/交付说明.md": "答辩材料\n",
            "scripts/backup.py": "# 备份源码\n",
            "experiments/runner.py": "# 实验源码\n",
        }.items():
            self.write(name, content)

    def write(self, relative, content="不应交付"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def live_result(self, relative="experiments/results/final-live"):
        self.write(relative + "/manifest.json", json.dumps({"run_mode": "live", "split": "eval"}))
        self.write(relative + "/summary.json", json.dumps({"run_mode": "live", "comparison_complete": False}))
        self.write(relative + "/records.json", "[]")
        return relative

    def test_only_fixed_roots_current_build_and_safe_names_are_read(self):
        excluded = [
            ".env", ".env.stitch", "data/jwt.key", "data/collaboration.db",
            "private.txt", "frontend/node_modules/pkg/index.js", "frontend/.npmrc",
            "backend/__pycache__/a.pyc", "backend/.pytest_cache/state",
            "backend/data/collaboration.db", "docs/private.pem", "docs/jwt.key",
            "scripts/.env.example", "scripts/.env.local", "scripts/secrets.json",
            "docs/credentials.json", "docs/database.sqlite3", "work/other-report.json",
            "experiments/results/offline/manifest.json",
        ]
        for name in excluded:
            self.write(name)
        module = load_package()
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(path.relative_to(self.root).as_posix(), excluded,
                             "打包前就不应读取排除内容")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
            self.assertTrue({"README.md", ".env.example", "frontend/dist/index.html",
                             "frontend/package-lock.json", "experiments/runner.py"} <= names)
            self.assertTrue(names.isdisjoint(excluded))
            self.assertTrue(all(n.split("/")[0] in {"README.md", ".env.example", "backend", "frontend",
                                                   "docs", "scripts", "experiments", "manifest.json"} for n in names))

    def test_zip_is_reproducible_utf8_and_every_payload_has_sha256(self):
        module = load_package()
        first = module.create_delivery(self.root, "work/delivery/first.zip")
        for file in self.root.rglob("*"):
            if file.is_file() and "work" not in file.relative_to(self.root).parts:
                os.utime(file, (1800000000, 1800000000))
        second = module.create_delivery(self.root, "work/delivery/second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as package:
            manifest = json.loads(package.read("manifest.json").decode("utf-8"))
            self.assertEqual({row["path"] for row in manifest["files"]}, set(package.namelist()) - {"manifest.json"})
            for row in manifest["files"]:
                payload = package.read(row["path"])
                self.assertEqual(row["sha256"], hashlib.sha256(payload).hexdigest())
                self.assertEqual(row["size"], len(payload))
            info = package.getinfo("docs/交付说明.md")
            self.assertTrue(info.flag_bits & 0x800)
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
        self.assertEqual(module.verify_delivery(first)["files_count"], len(manifest["files"]))

    def test_sqlite_sidecars_are_excluded_before_reading_even_with_live_wal(self):
        module = load_package()
        database = self.root / "docs/synthetic.sqlite3"
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE synthetic (payload TEXT)")
        marker = "delivery-regression-synthetic-only"
        connection.execute("INSERT INTO synthetic VALUES (?)", (marker,))
        connection.commit()
        wal = Path(str(database) + "-wal")
        self.assertIn(marker.encode("ascii"), wal.read_bytes(), "先确认真实 WAL 含合成行")
        self.assertTrue(Path(str(database) + "-shm").exists())
        excluded = {database.relative_to(self.root).as_posix()}
        for directory in ("docs", "work/checks"):
            for extension in ("db", "sqlite", "sqlite3"):
                for sidecar in ("wal", "shm", "journal"):
                    name = f"{directory}/synthetic.{extension}-{sidecar}"
                    if not (self.root / name).exists():
                        self.write(name, "仅用于测试的数据库旁路内容")
                    excluded.add(name)
            excluded.add(f"{directory}/UPPER.SQLITE3-JOURNAL")
            self.write(f"{directory}/UPPER.SQLITE3-JOURNAL", "仅用于大小写测试")
        self.write("work/checks/result.json", '{"synthetic":true}')
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(path.relative_to(self.root).as_posix(), excluded,
                             "数据库及 WAL/SHM/journal 必须在读取前排除")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root, evidence=["work/checks"])
        with zipfile.ZipFile(archive) as package:
            self.assertTrue(set(package.namelist()).isdisjoint(excluded))
            self.assertIn("work/checks/result.json", package.namelist())

    def test_explicit_database_sidecar_evidence_is_refused(self):
        module = load_package()
        for extension in ("db", "sqlite", "sqlite3"):
            for sidecar in ("wal", "shm", "journal"):
                relative = f"work/checks/synthetic.{extension}-{sidecar}"
                self.write(relative, "仅用于路径校验的合成内容")
                with self.subTest(path=relative), self.assertRaises(ValueError):
                    module.create_delivery(self.root, f"work/delivery/{extension}-{sidecar}.zip", evidence=[relative])

    def test_results_are_explicit_and_partial_live_status_is_preserved(self):
        module = load_package()
        result = self.live_result()
        self.write("experiments/results/other/records.json", "不可自动选择")
        archive = module.create_delivery(self.root, result_dirs=[result])
        with zipfile.ZipFile(archive) as package:
            self.assertIn(result + "/records.json", package.namelist())
            self.assertNotIn("experiments/results/other/records.json", package.namelist())
            summary = json.loads(package.read(result + "/summary.json"))
            self.assertIs(summary["comparison_complete"], False)
            manifest = json.loads(package.read("manifest.json"))
            self.assertEqual(manifest["result_directories"], [result])

    def test_dry_run_fixture_and_unqualified_results_are_refused(self):
        module = load_package()
        candidates = ["experiments/results/dry", "experiments/tests/fixtures/fake-live",
                      "work/model-results", "experiments/results"]
        self.write(candidates[0] + "/manifest.json", '{"run_mode":"dry_run"}')
        self.live_result(candidates[1])
        self.live_result(candidates[2])
        for index, candidate in enumerate(candidates):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                module.create_delivery(self.root, f"work/delivery/refused-{index}.zip", result_dirs=[candidate])

    def test_both_result_trees_are_excluded_before_reading_by_default(self):
        module = load_package()
        result_roots = ["experiments/results", "experiments/reliability_v3/results"]
        for result_root in result_roots:
            self.live_result(result_root + "/live")
            self.write(result_root + "/dry/manifest.json", '{"run_mode":"dry_run"}')
            self.write(result_root + "/dry/records.json", "仅用于测试的离线结果")
        self.write("experiments/reliability_v3/runner.py", "# v3 实验源码\n")
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            for result_root in result_roots:
                self.assertFalse(path.is_relative_to(self.root / result_root),
                                 "默认打包不得读取任一结果树中的 live 或 dry-run")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            self.assertIn("experiments/reliability_v3/runner.py", package.namelist())
            for result_root in result_roots:
                self.assertFalse(any(name.startswith(result_root + "/") for name in package.namelist()))
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [])

    def test_case_variants_of_both_result_trees_are_excluded_before_reading(self):
        module = load_package()
        result_roots = ["experiments/RESULTS", "experiments/reliability_v3/RESULTS",
                        "experiments/ReLiAbIlItY_V3/ReSuLtS"]
        original_open = Path.open
        for index, result_root in enumerate(result_roots):
            prefix = f"case-{index}"
            case_root = self.root / prefix
            self.live_result(f"{prefix}/{result_root}/live")
            self.write(f"{prefix}/{result_root}/dry/manifest.json", '{"run_mode":"dry_run"}')
            self.write(f"{prefix}/{result_root}/dry/records.json", "仅用于测试的离线结果")
            self.write(f"{prefix}/{Path(result_root).parent.as_posix()}/runner.py", "# 实验源码\n")

            def guarded_open(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(case_root / result_root),
                                 "大小写变体结果树中的 live 和 dry-run 均不得默认读取")
                return original_open(path, *args, **kwargs)

            with self.subTest(result_root=result_root):
                with patch.object(Path, "open", guarded_open):
                    archive = module.create_delivery(case_root)
                with zipfile.ZipFile(archive) as package:
                    names = [name.casefold() for name in package.namelist()]
                    self.assertFalse(any(name.startswith(result_root.casefold() + "/") for name in names))
                    self.assertTrue(any(name.endswith("/runner.py") for name in names))
                    self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [])

    def test_case_variants_of_fixed_result_roots_accept_explicit_live_runs(self):
        module = load_package()
        result_roots = ["experiments/RESULTS", "experiments/reliability_v3/RESULTS",
                        "ExPeRiMeNtS/ReLiAbIlItY_V3/ReSuLtS"]
        for index, result_root in enumerate(result_roots):
            prefix = f"case-{index}"
            case_root = self.root / prefix
            self.live_result(f"{prefix}/{result_root}/live")
            result = result_root + "/live"
            with self.subTest(result_root=result_root):
                archive = module.create_delivery(case_root, result_dirs=[result])
                with zipfile.ZipFile(archive) as package:
                    self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
                    self.assertIn(result + "/records.json", package.namelist())

    def test_explicit_v3_live_selection_reads_only_that_run_and_keeps_partial_status(self):
        module = load_package()
        result = self.live_result("experiments/reliability_v3/results/final-live")
        excluded_runs = [self.live_result(), self.live_result("experiments/reliability_v3/results/other-live"),
                         "experiments/reliability_v3/results/dry"]
        self.write(excluded_runs[-1] + "/manifest.json", '{"run_mode":"dry_run"}')
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            for excluded_run in excluded_runs:
                self.assertFalse(path.is_relative_to(self.root / excluded_run),
                                 "显式选择不得读取其他运行")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root, result_dirs=[result])
        with zipfile.ZipFile(archive) as package:
            result_names = {name for name in package.namelist()
                            if name.startswith(("experiments/results/", "experiments/reliability_v3/results/"))}
            self.assertEqual(result_names, {result + "/" + name
                                           for name in ("manifest.json", "summary.json", "records.json")})
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
            self.assertIs(json.loads(package.read(result + "/summary.json"))["comparison_complete"], False)

    def test_v3_dry_run_root_nested_and_unrecognized_results_are_refused(self):
        module = load_package()
        dry = "experiments/reliability_v3/results/dry"
        self.write(dry + "/manifest.json", '{"run_mode":"dry_run"}')
        candidates = [dry, "experiments/reliability_v3/results",
                      self.live_result("experiments/reliability_v3/results/final-live/nested"),
                      self.live_result("experiments/results/final-live/nested"),
                      self.live_result("experiments/other/results/fake-live"),
                      self.live_result("experiments/reliability_v3/archive/results/fake-live")]
        for index, candidate in enumerate(candidates):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                module.create_delivery(self.root, f"work/delivery/refused-v3-{index}.zip", result_dirs=[candidate])
            self.assertFalse((self.root / f"work/delivery/refused-v3-{index}.zip").exists())

    def test_selected_v3_live_run_rejects_links_and_reparse_points(self):
        module = load_package()
        result = self.live_result("experiments/reliability_v3/results/final-live")
        original_lstat = Path.lstat
        for selected in [result, result + "/manifest.json", result + "/records.json"]:
            for metadata in [SimpleNamespace(st_mode=0o120777, st_file_attributes=0),
                             SimpleNamespace(st_mode=0o040777, st_file_attributes=0x400)]:
                def linked_lstat(path, *args, **kwargs):
                    if path == self.root / selected:
                        return metadata
                    return original_lstat(path, *args, **kwargs)

                with self.subTest(path=selected, metadata=metadata), patch.object(Path, "lstat", linked_lstat):
                    with self.assertRaisesRegex(ValueError, "符号链接|重解析点"):
                        module.create_delivery(self.root, result_dirs=[result])

    def test_selected_v3_live_run_excludes_database_sidecars_before_reading(self):
        module = load_package()
        result = self.live_result("experiments/reliability_v3/results/final-live")
        excluded = set()
        for extension in ("db", "sqlite", "sqlite3"):
            for sidecar in ("", "-wal", "-shm", "-journal"):
                relative = f"{result}/synthetic.{extension}{sidecar}"
                self.write(relative, "仅用于测试的合成数据库旁路内容")
                excluded.add(relative)
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(path.relative_to(self.root).as_posix(), excluded,
                             "显式结果中的数据库及旁路文件必须在读取前排除")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root, result_dirs=[result])
        with zipfile.ZipFile(archive) as package:
            self.assertTrue(set(package.namelist()).isdisjoint(excluded))
            self.assertIn(result + "/records.json", package.namelist())

    def test_cli_results_dir_selects_explicit_v3_live_run(self):
        load_package()
        result = self.live_result("experiments/reliability_v3/results/final-live")
        created = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root),
                                  "--results-dir", result],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(created.returncode, 0, created.stderr)
        with zipfile.ZipFile(json.loads(created.stdout)["archive"]) as package:
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
            self.assertIn(result + "/records.json", package.namelist())

    def test_followup_results_are_skipped_before_stat_traversal_or_reading_by_default(self):
        module = load_package()
        result_root = "experiments/reliability_followup/results"
        self.live_result(result_root + "/live")
        self.write(result_root + "/dry/manifest.json", '{"run_mode":"dry_run"}')
        self.write("experiments/reliability_followup/runner.py", "# followup 实验源码\n")

        def guard(original):
            def guarded(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(self.root / result_root),
                                 "默认打包必须在访问、遍历或读取 followup 结果树前跳过")
                return original(path, *args, **kwargs)
            return guarded

        with patch.object(Path, "lstat", guard(Path.lstat)), \
                patch.object(Path, "iterdir", guard(Path.iterdir)), \
                patch.object(Path, "open", guard(Path.open)):
            archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            self.assertIn("experiments/reliability_followup/runner.py", package.namelist())
            self.assertFalse(any(name.startswith(result_root + "/") for name in package.namelist()))
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [])

    def test_case_variants_of_followup_results_are_excluded_before_reading(self):
        module = load_package()
        result_roots = ["experiments/reliability_followup/RESULTS",
                        "ExPeRiMeNtS/ReLiAbIlItY_FoLlOwUp/ReSuLtS"]
        original_open = Path.open
        for index, result_root in enumerate(result_roots):
            prefix = f"case-{index}"
            case_root = self.root / prefix
            self.live_result(f"{prefix}/{result_root}/live")
            self.write(f"{prefix}/{result_root}/dry/manifest.json", '{"run_mode":"dry_run"}')
            self.write(f"{prefix}/{Path(result_root).parent.as_posix()}/runner.py", "# 实验源码\n")

            def guarded_open(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(case_root / result_root),
                                 "大小写变体 followup 结果树不得默认读取")
                return original_open(path, *args, **kwargs)

            with self.subTest(result_root=result_root):
                with patch.object(Path, "open", guarded_open):
                    archive = module.create_delivery(case_root)
                with zipfile.ZipFile(archive) as package:
                    self.assertFalse(any(name.casefold().startswith(result_root.casefold() + "/")
                                         for name in package.namelist()))
                    self.assertTrue(any(name.endswith("/runner.py") for name in package.namelist()))

    def test_explicit_followup_live_selection_reads_only_that_run_and_keeps_partial_status(self):
        module = load_package()
        result = self.live_result("experiments/reliability_followup/results/final-live")
        excluded_runs = [self.live_result(), self.live_result("experiments/reliability_v3/results/other-live"),
                         self.live_result("experiments/reliability_followup/results/other-live"),
                         "experiments/reliability_followup/results/dry"]
        self.write(excluded_runs[-1] + "/manifest.json", '{"run_mode":"dry_run"}')
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            for excluded_run in excluded_runs:
                self.assertFalse(path.is_relative_to(self.root / excluded_run),
                                 "显式选择不得读取其他运行或其他结果根")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root, result_dirs=[result])
        with zipfile.ZipFile(archive) as package:
            result_names = {name for name in package.namelist() if name.startswith(
                ("experiments/results/", "experiments/reliability_v3/results/",
                 "experiments/reliability_followup/results/"))}
            self.assertEqual(result_names, {result + "/" + name
                                           for name in ("manifest.json", "summary.json", "records.json")})
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
            self.assertIs(json.loads(package.read(result + "/summary.json"))["comparison_complete"], False)

    def test_case_variants_of_followup_result_root_accept_explicit_live_runs(self):
        module = load_package()
        result_roots = ["experiments/reliability_followup/RESULTS",
                        "ExPeRiMeNtS/ReLiAbIlItY_FoLlOwUp/ReSuLtS"]
        for index, result_root in enumerate(result_roots):
            prefix = f"case-{index}"
            case_root = self.root / prefix
            self.live_result(f"{prefix}/{result_root}/live")
            result = result_root + "/live"
            with self.subTest(result_root=result_root):
                archive = module.create_delivery(case_root, result_dirs=[result])
                with zipfile.ZipFile(archive) as package:
                    self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
                    self.assertIn(result + "/records.json", package.namelist())

    def test_followup_dry_fixture_root_nested_and_unrecognized_results_are_refused(self):
        module = load_package()
        dry = "experiments/reliability_followup/results/dry"
        fixture = "experiments/reliability_followup/results/fixture"
        unmarked = "experiments/reliability_followup/results/unmarked"
        for relative, content in [(dry, '{"run_mode":"dry_run"}'),
                                  (fixture, '{"run_mode":"fixture"}'), (unmarked, '{}')]:
            self.write(relative + "/manifest.json", content)
        candidates = [dry, fixture, unmarked, "experiments/reliability_followup/results",
                      self.live_result("experiments/reliability_followup/results/final-live/nested"),
                      self.live_result("experiments/reliability_followup/archive/results/fake-live"),
                      self.live_result("experiments/reliability_followup_extra/results/fake-live"),
                      self.live_result("experiments/reliability_followup/results-extra/fake-live"),
                      self.live_result("EXPERIMENTS/RELIABILITY_FOLLOWUP/archive/RESULTS/fake-live"),
                      self.live_result("EXPERIMENTS/RELIABILITY_FOLLOWUP_EXTRA/RESULTS/fake-live")]
        for index, candidate in enumerate(candidates):
            output = f"work/delivery/refused-followup-{index}.zip"
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                module.create_delivery(self.root, output, result_dirs=[candidate])
            self.assertFalse((self.root / output).exists())

    def test_followup_exclusion_does_not_expand_to_similarly_named_or_nested_results(self):
        module = load_package()
        included = ["experiments/reliability_followup/archive/results/source.txt",
                    "experiments/reliability_followup/results-extra/source.txt",
                    "experiments/reliability_followup_extra/results/source.txt",
                    "experiments/OTHER/RESULTS/source.txt"]
        for relative in included:
            self.write(relative, "固定结果根之外的源码样例")
        archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            self.assertTrue(set(included) <= set(package.namelist()))

    def test_selected_followup_live_run_rejects_links_and_reparse_points(self):
        module = load_package()
        result = self.live_result("experiments/reliability_followup/results/final-live")
        original_lstat = Path.lstat
        for selected in ["experiments/reliability_followup/results", result,
                         result + "/manifest.json", result + "/records.json"]:
            for metadata in [SimpleNamespace(st_mode=0o120777, st_file_attributes=0),
                             SimpleNamespace(st_mode=0o040777, st_file_attributes=0x400)]:
                def linked_lstat(path, *args, **kwargs):
                    if path == self.root / selected:
                        return metadata
                    return original_lstat(path, *args, **kwargs)

                with self.subTest(path=selected, metadata=metadata), patch.object(Path, "lstat", linked_lstat):
                    with self.assertRaisesRegex(ValueError, "符号链接|重解析点"):
                        module.create_delivery(self.root, result_dirs=[result])

    def test_selected_followup_live_run_excludes_database_sidecars_before_reading(self):
        module = load_package()
        result = self.live_result("experiments/reliability_followup/results/final-live")
        excluded = set()
        for extension in ("db", "sqlite", "sqlite3"):
            for sidecar in ("", "-wal", "-shm", "-journal"):
                relative = f"{result}/synthetic.{extension}{sidecar}"
                self.write(relative, "仅用于测试的合成数据库旁路内容")
                excluded.add(relative)
        for name in ["UPPER.SQLITE3-WAL", ".env", "jwt.key"]:
            relative = result + "/" + name
            self.write(relative, "仅用于测试的排除内容")
            excluded.add(relative)
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(path.relative_to(self.root).as_posix(), excluded,
                             "显式 followup 结果中的数据库、旁路文件和凭据必须在读取前排除")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            archive = module.create_delivery(self.root, result_dirs=[result])
        with zipfile.ZipFile(archive) as package:
            self.assertTrue(set(package.namelist()).isdisjoint(excluded))
            self.assertIn(result + "/records.json", package.namelist())

    def test_cli_results_dir_selects_explicit_followup_live_run(self):
        load_package()
        result = self.live_result("experiments/reliability_followup/results/final-live")
        created = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--root", str(self.root),
                                  "--results-dir", result],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(created.returncode, 0, created.stderr)
        with zipfile.ZipFile(json.loads(created.stdout)["archive"]) as package:
            self.assertEqual(json.loads(package.read("manifest.json"))["result_directories"], [result])
            self.assertIn(result + "/records.json", package.namelist())

    def test_evidence_is_opt_in_and_keeps_project_relative_paths(self):
        module = load_package()
        self.write("work/checks/答辩检查.json", '{"passed":true}')
        self.write("work/acceptance/run-01/result.json", '{"checks":50}')
        self.write("work/acceptance/run-01/jwt.key")
        self.write("work/acceptance/run-01/data/collaboration.db")
        self.write("work/acceptance/run-02/result.json")
        self.write("work/backups/collaboration.db")
        archive = module.create_delivery(self.root, evidence=["work/checks/答辩检查.json", "work/acceptance/run-01"])
        with zipfile.ZipFile(archive) as package:
            work_names = {n for n in package.namelist() if n.startswith("work/")}
            self.assertEqual(work_names, {"work/checks/答辩检查.json", "work/acceptance/run-01/result.json"})

    def test_evidence_cannot_select_all_work_data_secrets_or_output(self):
        module = load_package()
        for name in ["work/jwt.key", "work/collaboration.db", "data/report.json", "work/delivery/nested/report.json"]:
            self.write(name)
        for index, candidate in enumerate(["work", "data/report.json", "work/jwt.key", "work/collaboration.db", "work/delivery"]):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                module.create_delivery(self.root, f"work/delivery/refused-{index}.zip", evidence=[candidate])

    def test_output_cannot_escape_delivery_or_overwrite_existing_files(self):
        module = load_package()
        original = self.write("work/delivery/kept.zip", "原归档")
        invalid = ["data/overwrite.zip", "work/outside.zip", "work/delivery/../escape.zip",
                   "../outside.zip", "work/delivery/file.txt", str(self.root.parent / "outside.zip")]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                module.create_delivery(self.root, candidate)
        with self.assertRaises(FileExistsError):
            module.create_delivery(self.root, original)
        self.assertEqual(original.read_text(encoding="utf-8"), "原归档")

    def test_input_traversal_is_refused_even_when_normalization_stays_inside(self):
        module = load_package()
        self.write("work/report.json", "{}")
        self.live_result()
        for kwargs in [{"evidence": ["work/checks/../report.json"]},
                       {"evidence": [str(self.root.parent / "outside.txt")]},
                       {"result_dirs": ["experiments/results/../results/final-live"]}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                module.create_delivery(self.root, **kwargs)

    def test_symlinks_in_selected_source_evidence_and_output_are_refused(self):
        module = load_package()
        target = self.write("outside-safe/report.txt", "链接目标").parent

        def directory_link(link, target_path):
            try:
                link.symlink_to(target_path, target_is_directory=True)
            except OSError:
                if os.name != "nt":
                    raise
                import _winapi
                _winapi.CreateJunction(str(target_path), str(link))

        link = self.root / "docs" / "linked"
        directory_link(link, target)
        with self.assertRaises(ValueError):
            module.create_delivery(self.root)
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()  # 只移除已确认的临时 junction，不遍历其目标。
        evidence_link = self.root / "work" / "linked"
        evidence_link.parent.mkdir(exist_ok=True)
        directory_link(evidence_link, target)
        with self.assertRaises(ValueError):
            module.create_delivery(self.root, evidence=["work/linked"])
        directory_link(self.root / "work" / "delivery", self.root / "docs")
        with self.assertRaises(ValueError):
            module.create_delivery(self.root)

    def test_link_and_windows_reparse_metadata_fail_closed_without_link_privileges(self):
        module = load_package()
        self.write("work/report.json", "{}")
        original_lstat = Path.lstat
        for selected, kwargs in [("docs/交付说明.md", {}),
                                 ("work/report.json", {"evidence": ["work/report.json"]}),
                                 ("work/delivery", {})]:
            for metadata in [SimpleNamespace(st_mode=0o120777, st_file_attributes=0),
                             SimpleNamespace(st_mode=0o040777, st_file_attributes=0x400)]:
                def linked_lstat(path, *args, **call_kwargs):
                    if path == self.root / selected:
                        return metadata
                    return original_lstat(path, *args, **call_kwargs)

                with self.subTest(path=selected, metadata=metadata), patch.object(Path, "lstat", linked_lstat):
                    with self.assertRaisesRegex(ValueError, "符号链接|重解析点"):
                        module.create_delivery(self.root, **kwargs)
    def test_verification_rejects_changed_payload_and_undeclared_files(self):
        module = load_package()
        archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            infos = {info.filename: info for info in package.infolist()}
            payloads = {name: package.read(name) for name in package.namelist()}
        for index, modification in enumerate([{ "README.md": b"tampered" }, {"extra.txt": b"undeclared"}]):
            changed = self.root / "work" / "delivery" / f"changed-{index}.zip"
            with zipfile.ZipFile(changed, "w") as package:
                for name, content in (payloads | modification).items():
                    info = infos.get(name, zipfile.ZipInfo(name))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    package.writestr(info, content)
            error = "SHA-256" if index == 0 else "文件集合"
            with self.subTest(modification=modification), self.assertRaisesRegex(ValueError, error):
                module.verify_delivery(changed)

    def test_verification_accepts_regular_zip_metadata_without_file_type_bits(self):
        module = load_package()
        archive = module.create_delivery(self.root)
        with zipfile.ZipFile(archive) as package:
            payloads = {name: package.read(name) for name in package.namelist()}
        portable = self.root / "work/delivery/portable.zip"
        with zipfile.ZipFile(portable, "w") as package:
            for name, content in payloads.items():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = 0o600 << 16
                package.writestr(info, content)
        self.assertGreater(module.verify_delivery(portable)["files_count"], 0)

    def test_cli_package_and_verify_are_offline(self):
        load_package()
        created = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(created.returncode, 0, created.stderr)
        archive = json.loads(created.stdout)["archive"]
        checked = subprocess.run([sys.executable, str(SCRIPT), "--verify", archive],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertGreater(json.loads(checked.stdout)["files_count"], 0)


if __name__ == "__main__":
    unittest.main()
