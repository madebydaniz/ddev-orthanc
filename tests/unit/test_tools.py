import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "orthanc_tools", ROOT / "orthanc/tools/orthanc.py"
)
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


class ToolsTest(unittest.TestCase):
    def test_doctor_self_echo_uses_effective_port_and_aet(self):
        def response(path, data=None):
            if path == "/system":
                return {"Version": "synthetic", "DicomAet": "CUSTOM"}
            if path == "/plugins":
                return ["orthanc-explorer-2"]
            return {}

        output = io.StringIO()
        with (
            patch.object(tools, "request", side_effect=response) as request,
            patch.object(tools, "effective_config", return_value={"DicomPort": 4424}),
            redirect_stdout(output),
        ):
            tools.doctor()
        self.assertEqual(
            request.call_args_list[-1].args,
            (
                "/tools/dicom-echo",
                {
                    "AET": "CUSTOM",
                    "Host": "127.0.0.1",
                    "Port": 4424,
                    "Timeout": 2,
                    "CheckFind": False,
                },
            ),
        )
        self.assertIn("DICOM C-ECHO: passed", output.getvalue())
        self.assertFalse(
            any("/modalities" in call.args[0] for call in request.call_args_list)
        )

    def test_doctor_reports_disabled_server_without_echo(self):
        output = io.StringIO()
        with (
            patch.object(
                tools,
                "request",
                side_effect=[{"Version": "synthetic", "DicomAet": "CUSTOM"}, {}, []],
            ) as request,
            patch.object(
                tools, "effective_config", return_value={"DicomServerEnabled": False}
            ),
            redirect_stdout(output),
        ):
            tools.doctor()
        self.assertEqual(request.call_count, 3)
        self.assertIn("disabled (DicomServerEnabled=false)", output.getvalue())

    def test_doctor_echo_failure_exits_nonzero_and_ready_remains_passive(self):
        output, error = io.StringIO(), io.StringIO()
        with (
            patch.object(tools.sys, "argv", ["orthanc.py", "doctor"]),
            patch.object(tools, "effective_config", return_value={}),
            patch.object(
                tools,
                "request",
                side_effect=[
                    {"Version": "synthetic", "DicomAet": "ORTHANC"},
                    {},
                    [],
                    ValueError("Orthanc API /tools/dicom-echo: HTTP 502"),
                ],
            ),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            self.assertEqual(tools.main(), 1)
        self.assertNotIn("C-ECHO: passed", output.getvalue())
        self.assertIn("HTTP 502", error.getvalue())
        with (
            patch.object(tools.sys, "argv", ["orthanc.py", "ready"]),
            patch.object(tools, "request", return_value={}) as request,
        ):
            self.assertEqual(tools.main(), 0)
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["/system", "/changes?last"],
        )

    def test_seed_is_deterministic_valid_dicom(self):
        payload = tools.seed_dicom()
        self.assertEqual(payload, tools.seed_dicom())
        self.assertEqual(payload[128:132], b"DICM")
        self.assertIn(tools.SEED_UID.encode(), payload)
        self.assertIn(b"SYNTHETIC^DDEV", payload)
        self.assertLess(len(payload), 1024)

    def test_api_failures_hide_body_and_credentials(self):
        error = urllib.error.HTTPError(
            "http://localhost", 401, "secret response", {}, io.BytesIO(b"password")
        )
        with (
            patch.object(
                tools,
                "effective_config",
                return_value={"RegisteredUsers": {"user": "secret"}},
            ),
            patch.object(tools.urllib.request, "urlopen", side_effect=error),
            self.assertRaisesRegex(ValueError, "^Orthanc API /system: HTTP 401$"),
        ):
            tools.request("/system")

    def test_api_uses_basic_auth_and_dicom_content_type(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"Status": "Success"}'

        with (
            patch.object(
                tools,
                "effective_config",
                return_value={"RegisteredUsers": {"user": "secret"}},
            ),
            patch.object(
                tools.urllib.request, "urlopen", return_value=Response()
            ) as send,
        ):
            self.assertEqual(
                tools.request("/instances", tools.seed_dicom())["Status"], "Success"
            )
            request = send.call_args.args[0]
            self.assertEqual(request.get_header("Content-type"), "application/dicom")
            self.assertTrue(request.get_header("Authorization").startswith("Basic "))

    def test_backend_rejects_external_storage(self):
        effective = {
            "StorageDirectory": str(tools.STORAGE),
            "IndexDirectory": str(tools.STORAGE),
        }
        tools.validate_backend(effective, tools.IMAGE)
        for changes in (
            {"StorageDirectory": "relative"},
            {"PostgreSQL": {"EnableIndex": True}},
        ):
            with self.assertRaises(ValueError):
                tools.validate_backend({**effective, **changes}, tools.IMAGE)

    def test_backup_restore_round_trip_and_private_permissions(self):
        with tempfile.TemporaryDirectory(prefix="orthanc test ") as work:
            root = Path(work)
            source = root / "source"
            source.mkdir()
            (source / "index").write_bytes(b"sqlite fixture")
            config = root / "config"
            file = config / tools.CONFIG_FILES[0]
            file.parent.mkdir(parents=True)
            file.write_text('{"Name":"custom"}')
            local = config / ".env.orthanc.local"
            local.write_text("PRIVATE=true")
            archive = root / "backup with spaces.tar.gz"
            tools.backup(archive, tools.IMAGE, source, config)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                tools.backup(archive, tools.IMAGE, source, config)
            target = root / "target"
            target.mkdir()
            target_config = root / "restored"
            tools.restore(archive, tools.IMAGE, target, target_config)
            self.assertEqual((target / "index").read_bytes(), b"sqlite fixture")
            self.assertEqual(
                (target_config / ".env.orthanc.local").read_text(), "PRIVATE=true"
            )
            with self.assertRaisesRegex(ValueError, "empty storage"):
                tools.restore(archive, tools.IMAGE, target, target_config)

    def test_archive_rejects_unsafe_members_before_writing(self):
        attacks = (
            "../outside",
            "/outside",
            "storage/../outside",
            "storage//index",
            "unexpected",
        )
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            target = root / "storage"
            target.mkdir()
            for attack in attacks:
                archive_path = root / "attack.tar.gz"
                with tarfile.open(archive_path, "w:gz") as archive:
                    tools.add_bytes(
                        archive,
                        "manifest.json",
                        json.dumps(
                            {"format": 1, "backend": "sqlite", "image": tools.IMAGE}
                        ).encode(),
                    )
                    directory = tarfile.TarInfo("storage")
                    directory.type = tarfile.DIRTYPE
                    archive.addfile(directory)
                    tools.add_bytes(archive, attack, b"data")
                with self.assertRaises(ValueError):
                    tools.restore(archive_path, tools.IMAGE, target, root / "config")
                self.assertEqual(list(target.iterdir()), [])
            for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
                with tarfile.open(archive_path, "w:gz") as archive:
                    member = tarfile.TarInfo("storage/link")
                    member.type = kind
                    member.linkname = "/outside"
                    archive.addfile(member)
                with self.assertRaises(ValueError):
                    tools.restore(archive_path, tools.IMAGE, target, root / "config")
                self.assertEqual(list(target.iterdir()), [])

    def test_mismatched_archive_image(self):
        with tempfile.TemporaryDirectory() as work:
            archive_path = Path(work) / "bad.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                tools.add_bytes(
                    archive,
                    "manifest.json",
                    json.dumps(
                        {"format": 1, "backend": "sqlite", "image": "old"}
                    ).encode(),
                )
                directory = tarfile.TarInfo("storage")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
            with (
                tarfile.open(archive_path) as archive,
                self.assertRaisesRegex(ValueError, "does not match"),
            ):
                tools.validated_members(archive, tools.IMAGE)

    def test_cli_launch_and_unknown_arguments(self):
        with tempfile.TemporaryDirectory() as work:
            executable = Path(work) / "ddev"
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n')
            executable.chmod(0o755)
            env = {**os.environ, "PATH": work + ":" + os.environ["PATH"]}
            command = ["bash", str(ROOT / "commands/host/orthanc")]
            url = subprocess.run(
                command + ["url"], env=env, text=True, capture_output=True, check=False
            )
            self.assertEqual(url.returncode, 0)
            self.assertEqual(url.stdout.strip(), "launch --print-url :8043")
            self.assertEqual(
                subprocess.run(
                    command + ["--unknown"], env=env, capture_output=True, check=False
                ).returncode,
                2,
            )
            self.assertEqual(
                subprocess.run(
                    command + ["restore", "data"],
                    env=env,
                    capture_output=True,
                    check=False,
                ).returncode,
                2,
            )


if __name__ == "__main__":
    unittest.main()
