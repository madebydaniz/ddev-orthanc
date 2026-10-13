import io
import json
import os
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

from test_tools import ROOT, tools


class InstallerTest(unittest.TestCase):
    def run_install(self, directory):
        install = (ROOT / "install.yaml").read_text()
        action = textwrap.dedent(
            install.split("  - |\n", 1)[1].split("\npost_install_actions:", 1)[0]
        )
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", action],
            cwd=directory,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_legacy_formats_and_custom_paths_are_preserved_and_rejected(self):
        examples = (
            '{"StorageDirectory":\n"StorageORTHANC"}',
            '{"StorageDirectory":"/custom/orthanc/db"}',
            '{"StorageDirectory":"/var/lib/orthanc/db","IndexDirectory":"/var/lib/orthanc/db"}',
        )
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            config = root / "orthanc/config/orthanc.json"
            config.parent.mkdir(parents=True)
            compose = root / "docker-compose.orthanc.yaml"
            compose.write_text(
                "services:\n  orthanc:\n    image: osimis/orthanc:latest\n"
            )
            for content in examples:
                config.write_text(content)
                result = self.run_install(root)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(config.read_text(), content)
                self.assertIn("osimis/orthanc", compose.read_text())

    def test_fresh_and_maintained_reinstall_and_explicit_migration(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.assertEqual(self.run_install(root).returncode, 0)
            config = root / "orthanc/config/orthanc.json"
            config.parent.mkdir(parents=True)
            config.write_text((ROOT / "orthanc/config/orthanc.json").read_text())
            compose = root / "docker-compose.orthanc.yaml"
            compose.write_text((ROOT / "docker-compose.orthanc.yaml").read_text())
            (root / ".env.orthanc").write_text((ROOT / ".env.orthanc").read_text())
            self.assertEqual(self.run_install(root).returncode, 0)
            (root / "orthanc/.managed-storage-v1").write_text("sqlite-volume-v1\n")
            compose.unlink()
            (root / ".env.orthanc").unlink()
            # Removal retains owned config and managed storage identity.
            self.assertEqual(self.run_install(root).returncode, 0)
            compose.write_text("image: osimis/orthanc:latest\n")
            self.assertEqual(self.run_install(root).returncode, 2)
            (root / "orthanc/.migration-ack").write_text("sqlite-volume-v1\n")
            self.assertEqual(self.run_install(root).returncode, 0)
            config.write_text(
                '{"StorageDirectory":"/custom","IndexDirectory":"/custom"}'
            )
            self.assertEqual(self.run_install(root).returncode, 2)

    def test_image_interpolation_recognizes_only_maintained_template(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            config = root / "orthanc/config/orthanc.json"
            config.parent.mkdir(parents=True)
            config.write_text((ROOT / "orthanc/config/orthanc.json").read_text())
            (root / ".env.orthanc").write_text((ROOT / ".env.orthanc").read_text())
            local = root / ".env.orthanc.local"
            local.write_text("ORTHANC_IMAGE=orthancteam/orthanc:26.4.2\n")
            compose = root / "docker-compose.orthanc.yaml"
            compose.write_text((ROOT / "docker-compose.orthanc.yaml").read_text())
            self.assertEqual(self.run_install(root).returncode, 0)
            self.assertIn("26.4.2", local.read_text())
            for image in (
                "osimis/orthanc:latest",
                "${LEGACY_IMAGE:-osimis/orthanc:latest}",
                "${ORTHANC_IMAGE}",
                "${ORTHANC_IMAGE:-orthancteam/orthanc:26.9.1}-legacy",
                "unverified/custom:latest",
            ):
                compose.write_text("image: " + image + "\n")
                self.assertEqual(self.run_install(root).returncode, 2, image)


class StoragePreflightTest(unittest.TestCase):
    def test_cloud_hybrid_encryption_and_unknown_plugins_rejected_before_archive(self):
        standard = {
            "StorageDirectory": str(tools.STORAGE),
            "IndexDirectory": str(tools.STORAGE),
        }
        unsafe = (
            {"AwsS3Storage": {}},
            {"AwsS3Storage": {"BucketName": "synthetic"}},
            {"AzureBlobStorage": {"ContainerName": "synthetic"}},
            {"GoogleCloudStorage": {"BucketName": "synthetic"}},
            {"AwsS3Storage": {"HybridMode": "WriteToObjectStorage"}},
            {"StorageEncryption": {"Enable": True}},
            {"FutureBackend": {"Enabled": True}},
            {"Plugins": ["/custom/storage.so"]},
            {"PythonScript": "/custom/register-storage.py"},
        )
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for settings in unsafe:
                effective = {**standard, **settings}
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    tools.add_bytes(
                        archive, "orthanc.json", json.dumps(effective).encode()
                    )
                destination = root / "must-not-exist.tar.gz"
                result = subprocess.run(
                    [
                        "python3",
                        str(ROOT / "orthanc/tools/orthanc.py"),
                        "validate-backup",
                        str(destination),
                        "--effective-stdin",
                    ],
                    input=stream.getvalue(),
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(destination.exists())

    def test_verified_default_and_disabled_database_sections_supported(self):
        effective = {
            "StorageDirectory": str(tools.STORAGE),
            "IndexDirectory": str(tools.STORAGE),
            "PostgreSQL": {"EnableIndex": False, "EnableStorage": False},
            "MySQL": {"EnableIndex": False, "EnableStorage": False},
            "ODBC": {"EnableIndex": False, "EnableStorage": False},
            "Plugins": ["/usr/share/orthanc/plugins"],
            "OHIF": {"Enable": True},
            "DicomWeb": {"Enable": True},
            "Gdcm": {"Enable": True},
            "OrthancExplorer2": {"Enable": True},
            "StoneWebViewer": {"Enable": True},
        }
        tools.validate_backend(effective, tools.IMAGE)


class HostOperationTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="orthanc-cli-test-")
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        (self.root / ".ddev/orthanc").mkdir(parents=True)
        self.lock = self.root / ".ddev/orthanc/.operation-lock"
        self.state = self.root / "state"
        self.state.write_text("true")
        self.log = self.root / "actions"
        docker = self.root / "docker"
        docker.write_text("""#!/usr/bin/env python3
import os, signal, sys
from pathlib import Path
root = Path(os.environ["MOCK_ROOT"])
args = sys.argv[1:]
state = root / "state"
lock = root / ".ddev/orthanc/.operation-lock"
event = args[0]
if event == "inspect":
    assert lock.is_dir(), "state inspected outside lock"
    image = ".Config.Image" in args[2]
    event = "inspect-image" if image else "inspect-running"
    print("orthancteam/orthanc:26.9.1" if image else state.read_text())
elif event == "cp":
    print("mock effective config")
elif event == "stop":
    state.write_text("false")
elif event == "start":
    state.write_text("true")
elif event == "run":
    sys.stdin.read()
    event = next(item for item in args if item in ("backup", "restore", "validate-backup", "validate-restore"))
with (root / "actions").open("a") as output:
    output.write(event + "\\n")
if event in ("backup", "restore"):
    assert state.read_text() == "false", "copy attempted against live database"
    if os.environ.get("MOCK_SIGNAL") == "TERM":
        os.kill(os.getppid(), signal.SIGTERM)
    sys.exit(int(os.environ.get("MOCK_RESULT", "0")))
if event.startswith("validate-"):
    sys.exit(int(os.environ.get("MOCK_PREFLIGHT_RESULT", "0")))
""")
        docker.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(self.root) + ":" + os.environ["PATH"],
            "DDEV_APPROOT": str(self.root),
            "DDEV_SITENAME": "synthetic",
            "MOCK_ROOT": str(self.root),
        }

    def run_command(self, command="backup", **settings):
        archive = self.root / "archive.tar.gz"
        args = ["bash", str(ROOT / "commands/host/orthanc"), command, str(archive)]
        if command == "restore":
            archive.touch()
            args.append("--yes")
        return subprocess.run(
            args,
            env={**self.env, **settings},
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def actions(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_busy_lock_reads_no_state_then_new_backup_observes_restarted_service(self):
        self.lock.mkdir()
        self.state.write_text("false")
        busy = self.run_command()
        self.assertEqual(busy.returncode, 2)
        self.assertEqual(self.actions(), [])
        self.assertTrue(self.lock.exists())
        # Simulate A restarting and releasing before B acquires the lock.
        self.state.write_text("true")
        self.lock.rmdir()
        result = self.run_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = self.actions()
        self.assertLess(actions.index("stop"), actions.index("backup"))
        self.assertLess(actions.index("backup"), actions.index("start"))
        self.assertFalse(self.lock.exists())

    def test_backup_failure_resumes_running_service_and_cleans_lock(self):
        result = self.run_command(MOCK_RESULT="7")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.state.read_text(), "true")
        self.assertEqual(self.actions()[-1], "start")
        self.assertFalse(self.lock.exists())

    def test_preflight_failure_leaves_running_service_untouched(self):
        result = self.run_command(MOCK_PREFLIGHT_RESULT="8")
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertNotIn("stop", self.actions())
        self.assertNotIn("start", self.actions())
        self.assertEqual(self.state.read_text(), "true")
        self.assertFalse(self.lock.exists())

    def test_stopped_backup_does_not_start_service(self):
        self.state.write_text("false")
        result = self.run_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("stop", self.actions())
        self.assertNotIn("start", self.actions())
        self.assertEqual(self.state.read_text(), "false")
        self.assertFalse(self.lock.exists())

    def test_backup_termination_resumes_service_and_releases_lock(self):
        result = self.run_command(MOCK_SIGNAL="TERM")
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertEqual(self.state.read_text(), "true")
        self.assertFalse(self.lock.exists())

    def test_restore_failure_remains_stopped_and_releases_lock(self):
        result = self.run_command("restore", MOCK_RESULT="9")
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual(self.state.read_text(), "false")
        self.assertNotIn("start", self.actions())
        self.assertFalse(self.lock.exists())
