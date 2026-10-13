# #ddev-generated
"""Container-local developer tools for the SQLite DDEV Orthanc service."""

import argparse
import base64
import io
import json
import os
import shutil
import struct
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

IMAGE = "orthancteam/orthanc:26.9.1"
CONFIG = Path("/mnt/ddev_config")
STORAGE = Path("/var/lib/orthanc/db")
CONFIG_FILES = (
    "orthanc/config/orthanc.json",
    "orthanc/scripts/script.lua",
    ".env.orthanc",
    ".env.orthanc.local",
)
SEED_UID = "1.2.826.0.1.3680043.10.543.20261013.1"


def load_json(path):
    return json.loads(
        "\n".join(
            line
            for line in Path(path).read_text().splitlines()
            if not line.lstrip().startswith("//")
        )
    )


def effective_config():
    generated = Path("/tmp/orthanc.json")
    config = load_json(
        generated if generated.exists() else CONFIG / "orthanc/config/orthanc.json"
    )
    if "ORTHANC__REGISTERED_USERS" in os.environ:
        config["RegisteredUsers"] = json.loads(os.environ["ORTHANC__REGISTERED_USERS"])
    return config


def request(path, data=None, raw=False, method=None):
    config = effective_config()
    users = config.get("RegisteredUsers", {})
    if not users:
        raise ValueError("No Orthanc API user configured.")
    username, password = next(iter(users.items()))
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    if isinstance(data, bytes):
        headers["Content-Type"] = "application/dicom"
    elif data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8042{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = response.read()
            return payload if raw else json.loads(payload)
    except urllib.error.HTTPError as error:
        raise ValueError(f"Orthanc API {path}: HTTP {error.code}") from None
    except urllib.error.URLError:
        raise ValueError("Orthanc API is unreachable.") from None


def dicom_element(group, element, vr, value):
    if isinstance(value, str):
        value = value.encode("ascii")
    if len(value) % 2:
        value += b"\0" if vr == "UI" else b" "
    tag = struct.pack("<HH", group, element) + vr.encode()
    if vr in ("OB", "OW", "SQ", "UN", "UT"):
        return tag + b"\0\0" + struct.pack("<I", len(value)) + value
    return tag + struct.pack("<H", len(value)) + value


def seed_dicom():
    # Explicit VR little endian, one synthetic 2x2 grayscale secondary capture.
    sop = "1.2.840.10008.5.1.4.1.1.7"
    el = dicom_element
    meta = b"".join(
        (
            el(2, 1, "OB", b"\0\1"),
            el(2, 2, "UI", sop),
            el(2, 3, "UI", SEED_UID),
            el(2, 0x10, "UI", "1.2.840.10008.1.2.1"),
            el(2, 0x12, "UI", "1.2.826.0.1.3680043.10.543"),
        )
    )
    tags = (
        (8, 0x16, "UI", sop),
        (8, 0x18, "UI", SEED_UID),
        (8, 0x20, "DA", "20261013"),
        (8, 0x30, "TM", "120000"),
        (8, 0x60, "CS", "OT"),
        (8, 0x64, "CS", "WSD"),
        (0x10, 0x10, "PN", "SYNTHETIC^DDEV"),
        (0x10, 0x20, "LO", "DDEV-SYNTHETIC"),
        (0x20, 0x0D, "UI", SEED_UID + ".1"),
        (0x20, 0x0E, "UI", SEED_UID + ".2"),
        (0x20, 0x11, "IS", "1"),
        (0x20, 0x13, "IS", "1"),
        (0x28, 2, "US", struct.pack("<H", 1)),
        (0x28, 4, "CS", "MONOCHROME2"),
        (0x28, 0x10, "US", struct.pack("<H", 2)),
        (0x28, 0x11, "US", struct.pack("<H", 2)),
        (0x28, 0x100, "US", struct.pack("<H", 8)),
        (0x28, 0x101, "US", struct.pack("<H", 8)),
        (0x28, 0x102, "US", struct.pack("<H", 7)),
        (0x28, 0x103, "US", struct.pack("<H", 0)),
        (0x7FE0, 0x10, "OB", bytes((0, 85, 170, 255))),
    )
    return (
        bytes(128)
        + b"DICM"
        + el(2, 0, "UL", struct.pack("<I", len(meta)))
        + meta
        + b"".join(el(*tag) for tag in tags)
    )


def doctor():
    system = request("/system")
    request("/changes?last")
    plugins = request("/plugins")
    print(f"Orthanc {system['Version']}: authenticated API and database ready")
    print("Plugins: " + ", ".join(plugins))
    config = effective_config()
    if config.get("DicomServerEnabled", True) is False:
        print("DICOM C-ECHO: disabled (DicomServerEnabled=false)")
        return
    request(
        "/tools/dicom-echo",
        {
            "AET": system["DicomAet"],
            "Host": "127.0.0.1",
            "Port": config.get("DicomPort", 4242),
            "Timeout": 2,
            "CheckFind": False,
        },
    )
    print("DICOM C-ECHO: passed")


def add_bytes(archive, name, payload):
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    member.mode = 0o600
    archive.addfile(member, io.BytesIO(payload))


def validate_backend(effective, image):
    if not isinstance(effective, dict):
        raise TypeError("Effective Orthanc configuration must be an object.")
    if image != IMAGE:
        raise ValueError(
            "Backup and restore require the pinned supported Orthanc image."
        )
    if any(
        effective.get(key) != str(STORAGE)
        for key in ("StorageDirectory", "IndexDirectory")
    ):
        raise ValueError(
            "Backup and restore require the add-on storage and index paths."
        )
    for plugin in ("PostgreSQL", "MySQL", "ODBC"):
        settings = effective.get(plugin, {})
        if not isinstance(settings, dict):
            raise TypeError("Unsupported database plugin configuration.")
        if settings.get("EnableIndex") or settings.get("EnableStorage"):
            raise ValueError("Backup and restore support SQLite storage only.")
    verified_sections = {
        "DicomModalities",
        "RegisteredUsers",
        "OrthancPeers",
        "HttpHeaders",
        "HttpClientHeaders",
        "DicomWeb",
        "Gdcm",
        "OHIF",
        "OrthancExplorer2",
        "StoneWebViewer",
        "PostgreSQL",
        "MySQL",
        "ODBC",
    }
    core_storage_options = {
        "StorageDirectory",
        "IndexDirectory",
        "StorageCompression",
        "StorageAccessOnFind",
        "StorageCommitmentReportsSize",
    }
    for key, settings in effective.items():
        if key in verified_sections:
            continue
        if key in ("PythonScript", "PythonScripts") and settings:
            raise ValueError(
                "Backup and restore reject unverified Python plugin hooks."
            )
        # Unknown plugin objects and storage transformations cannot establish
        # that the local volume contains every original DICOM payload.
        if isinstance(settings, dict):
            raise ValueError(  # noqa: TRY004 - valid object, unverified backend semantics
                "Backup and restore reject unverified plugin configuration."
            )
        if "storage" in key.lower() and key not in core_storage_options:
            raise ValueError(
                "Backup and restore reject nonstandard storage configuration."
            )
    if any(
        Path(path) != Path("/usr/share/orthanc/plugins")
        for path in effective.get("Plugins", [])
    ):
        raise ValueError("Backup and restore reject custom plugin paths.")


def backup(path, image, storage=STORAGE, config=CONFIG, effective=None):
    if effective is not None:
        validate_backend(effective, image)
    for item in storage.rglob("*"):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("Storage contains an unsupported link or special file.")
    manifest = {"format": 1, "backend": "sqlite", "image": image}
    # Exclusive creation protects existing archives and keeps secrets private.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with (
            os.fdopen(fd, "wb") as output,
            tarfile.open(fileobj=output, mode="w:gz") as archive,
        ):
            add_bytes(archive, "manifest.json", json.dumps(manifest).encode())
            if effective is not None:
                add_bytes(archive, "effective.json", json.dumps(effective).encode())
            archive.add(storage, arcname="storage", recursive=True)
            for name in CONFIG_FILES:
                source = config / name
                if source.exists():
                    if source.is_symlink() or not source.is_file():
                        raise ValueError("Configuration must contain regular files.")
                    archive.add(source, arcname="config/" + name, recursive=False)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    print("Backup created. Treat the archive as private: it contains credentials.")


def validated_members(archive, image):
    members = archive.getmembers()
    names = set()
    total = 0
    for member in members:
        name = member.name
        parts = PurePosixPath(name).parts
        if (
            name in names
            or not parts
            or name != str(PurePosixPath(name))
            or name.startswith("/")
            or "\\" in name
            or ".." in parts
        ):
            raise ValueError("Archive has an unsafe or duplicate path.")
        names.add(name)
        if not (member.isfile() or member.isdir()):
            raise ValueError("Archive links and special files are not allowed.")
        allowed = name in (
            "manifest.json",
            "effective.json",
            "storage",
        ) or name.startswith("storage/")
        allowed = allowed or name in {"config/" + file for file in CONFIG_FILES}
        if not allowed or (name.startswith("config/") and not member.isfile()):
            raise ValueError("Archive contains an unexpected member.")
        total += member.size
        if total > 10 * 1024**3:
            raise ValueError("Archive exceeds the 10 GiB expanded-size limit.")
    if "manifest.json" not in names or "storage" not in names:
        raise ValueError("Archive is missing its manifest or storage root.")
    manifest_member = archive.getmember("manifest.json")
    if not manifest_member.isfile() or manifest_member.size > 4096:
        raise ValueError("Invalid archive manifest.")
    manifest = json.load(archive.extractfile(manifest_member))
    if manifest != {"format": 1, "backend": "sqlite", "image": image}:
        raise ValueError("Archive format, storage backend or image does not match.")
    if "effective.json" in names:
        effective_member = archive.getmember("effective.json")
        if not effective_member.isfile() or effective_member.size > 1024**2:
            raise ValueError("Invalid effective configuration.")
        validate_backend(json.load(archive.extractfile(effective_member)), image)
    if not archive.getmember("storage").isdir():
        raise ValueError("Invalid storage root.")
    return members


def restore(path, image, storage=STORAGE, config=CONFIG, effective=None):
    config = config.resolve()
    if effective is not None:
        validate_backend(effective, image)
    if any(storage.iterdir()):
        raise ValueError(
            "Restore requires an empty storage volume; existing data was preserved."
        )
    with tarfile.open(path, "r:gz") as archive:
        members = validated_members(archive, image)
        # Validate and read every payload before writing any target file.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="orthanc-restore-") as staging:
            staged = Path(staging)
            for member in members:
                target = staged / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.extractfile(member) as source,
                        target.open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output)
                    target.chmod(0o600)
            for name in CONFIG_FILES:
                target = config / name
                parents = [
                    p for p in target.parents if p != config and config in p.parents
                ]
                if target.is_symlink() or any(p.is_symlink() for p in parents):
                    raise ValueError("Configuration target contains a symlink.")
            # Failure here intentionally leaves the service stopped and partial data for inspection.
            for item in (staged / "storage").iterdir():
                shutil.move(str(item), storage / item.name)
            for name in CONFIG_FILES:
                source = staged / "config" / name
                if source.exists():
                    target = config / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(0o600)
    print(
        "Restore completed. Orthanc remains stopped; run ddev restart to reload restored configuration."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "ready",
            "doctor",
            "seed",
            "backup",
            "restore",
            "validate-backup",
            "validate-restore",
        ),
    )
    parser.add_argument("archive", nargs="?")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--effective-stdin", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "ready":
            request("/system")
            request("/changes?last")
        elif args.command == "doctor":
            doctor()
        elif args.command == "seed":
            result = request("/instances", seed_dicom())
            print(json.dumps({key: result[key] for key in ("ID", "Status")}))
        else:
            if not args.archive:
                parser.error("archive path is required")
            effective = None
            if args.effective_stdin:
                with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as incoming:
                    entry = incoming.next()
                    if entry is None or not entry.isfile() or entry.size > 1024**2:
                        raise ValueError(
                            "Invalid effective configuration from container."
                        )
                    effective = json.load(incoming.extractfile(entry))
                    if incoming.next() is not None:
                        raise ValueError("Unexpected effective configuration stream.")
            if args.command.startswith("validate-"):
                validate_backend(effective, args.image)
                if args.command == "validate-restore":
                    if any(STORAGE.iterdir()):
                        raise ValueError(
                            "Restore requires an empty storage volume; existing data was preserved."
                        )
                    with tarfile.open(args.archive, "r:gz") as archive:
                        for member in validated_members(archive, args.image):
                            if member.isfile():
                                with archive.extractfile(member) as source:
                                    while source.read(1024**2):
                                        pass
                elif Path(args.archive).exists():
                    raise ValueError("Backup archive already exists.")
            else:
                globals()[args.command](args.archive, args.image, effective=effective)
    except (
        ValueError,
        TypeError,
        OSError,
        tarfile.TarError,
    ) as error:
        # Never echo API bodies or configuration that could contain credentials.
        print(f"Orthanc {args.command} failed: {error}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
