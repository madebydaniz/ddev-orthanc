# DDEV Orthanc

A lightweight local DICOM server for DDEV: SQLite, persistent storage and Orthanc Explorer 2. Requires DDEV **v1.25.4+** and Docker. The image is pinned to `orthancteam/orthanc:26.9.1` (Orthanc 1.13.0).

## Install

```bash
ddev add-on get madebydaniz/ddev-orthanc
ddev restart
ddev orthanc
```

These changes are currently in source; published release 0.0.4 still uses the older configuration. To test this checkout, install a source snapshot as described below.

## Access and configuration

| Client | Endpoint |
| --- | --- |
| Host browser/API | `https://<project>.ddev.site:8043` or `http://<project>.ddev.site:8042` |
| Another DDEV container | `http://orthanc:8042` |
| Host DICOM client | `127.0.0.1:4242`, called AET `ORTHANC` |
| Another DDEV container, DICOM | `orthanc:4242` |

`ddev orthanc url` prints the actual HTTPS URL using DDEV's launch conventions. DICOM is bound to localhost; the HTTP service is routed through DDEV rather than a random direct host port.

Development credentials default to **orthanc / orthanc**. Set project overrides in **.ddev/.env.orthanc.local**, which DDEV excludes from Git:

```dotenv
ORTHANC_DICOM_PORT=14242
ORTHANC__REGISTERED_USERS={"developer":"replace-this-password"}
ORTHANC__DICOM_AET=DEVORTHANC
DICOM_WEB_PLUGIN_ENABLED=true
OHIF_PLUGIN_ENABLED=true
```

Run `ddev restart` after changes. Every concurrently running project needs a distinct host DICOM port. The default login exists only in the environment defaults; replacing `ORTHANC__REGISTERED_USERS` removes it. These are local development credentials; keep real patient data out of disposable environments.

Orthanc Explorer 2 is enabled by default, at `/ui/app/`. DICOMweb is optional, at `/dicom-web/`. OHIF is optional, at `/ohif/`, and requires DICOMweb enabled. JSON lives at `.ddev/orthanc/config/orthanc.json`; Lua hooks live at `.ddev/orthanc/scripts/script.lua`. Image environment overrides take precedence. Keep storage and index at `/var/lib/orthanc/db` when using the command suite.

## Commands

| Command | Behavior |
| --- | --- |
| `ddev orthanc` / `launch` | Launch the HTTPS browser endpoint |
| `ddev orthanc url` | Print the HTTPS URL |
| `ddev orthanc doctor` | Check authenticated API, database readiness and plugins; C-ECHO when echoscu exists in the container |
| `ddev orthanc seed` | Upload one tiny synthetic 2×2 DICOM image with fixed UIDs |
| `ddev orthanc backup "/path/archive.tar.gz"` | Validate backend, stop only Orthanc, archive storage/config, resume it if previously running |
| `ddev orthanc restore "/path/archive.tar.gz" --yes` | Validate archive and empty target, restore, leave Orthanc stopped |
| `ddev orthanc help` | Show usage |

The original `-o` and `--orthanc` flags still launch the browser. Unknown arguments fail. Repeated seed calls return the same ID and `AlreadyStored`; this fixture contains synthetic data only. The pinned image has no echoscu, so doctor explicitly reports C-ECHO untested; use a host DCMTK client for that check:

```bash
echoscu -aec ORTHANC 127.0.0.1 4242
storescu -aec ORTHANC 127.0.0.1 4242 /path/synthetic.dcm
```

## Data, upgrades and removal

The project volume is named `ddev-<project>-orthanc-data`. Container recreation and add-on removal preserve it. Normal `ddev delete` does not establish a data-retention policy for you: retain backups and verify any volume cleanup separately.
Installation records the managed layout in `.ddev/orthanc/.managed-storage-v1`. This local metadata survives add-on removal so reinstalling a preserved standard config is recognized safely; it does not bypass checks when an old Compose image or custom storage path is present.

Generated files are managed by DDEV. To own a config/Lua/Compose file, remove its `#ddev-generated` marker before reinstalling. Reinstallation preserves files without the marker and all local environment overrides. No pre-install step deletes customized files.

The old add-on used relative `StorageORTHANC` storage inside its container. An upgrade detecting that configuration stops with migration guidance. Before changing anything:

1. Stop the old Orthanc container and copy its entire SQLite index and DICOM storage to a private backup.
2. Verify the backup and identify the actual old storage path; do not assume the old data already lives in a named volume.
3. Explicitly migrate the complete stopped storage into a new project volume, retaining the old backup.
4. Set both JSON storage paths to `/var/lib/orthanc/db`. Only after confirming the complete stopped data is in the correct named volume, explicitly acknowledge the migration with `printf '%s\n' 'sqlite-volume-v1' > .ddev/orthanc/.migration-ack`.
5. Install, restart and verify study/instance counts and retrieval. The acknowledgment permits replacing the old service layout; it does not copy data or bypass the standard storage/index path checks.

This migration is manual. Without that acknowledgment, an existing service must already have the maintained image/env layout and standard paths before reinstalling. Multiline JSON and custom legacy paths are rejected safely. The backup command supports only the pinned image, SQLite and standard absolute storage paths; enabled SQL/object-storage backends, storage transformations, unknown configured plugin objects and custom plugin paths are rejected. Disabled SQL stanzas and the verified bundled UI/DICOMweb/GDCM sections remain supported.

## Backup and restore

Archive directories must already exist. Names with spaces work. Archives are created exclusively with mode **0600**, include a format/backend/image manifest, effective runtime configuration, stopped SQLite storage, JSON, Lua, `.env.orthanc` and `.env.orthanc.local` when present. They contain credentials and must be stored privately. Compose customizations, other env files and external plugin resources are not included.

Backup validates the effective configuration before stopping. Failed backups resume an originally running Orthanc service. A previously stopped service remains stopped. Other DDEV services continue running.
Operations are serialized by a project lock. If a terminated host leaves `.ddev/orthanc/.operation-lock`, verify that no operation is still active before removing the empty lock directory.

Restore requires `--yes` and a physically empty volume. It rejects nonempty storage, path traversal, links, special files, unexpected layouts, duplicate paths and incompatible image/backend manifests. The expanded archive limit is 10 GiB. Validation errors leave the running service untouched; extraction failures leave Orthanc stopped with partial data available for inspection.

A freshly started Orthanc already initializes SQLite and therefore is not an empty restore target. For recovery, initialize a new DDEV project with this add-on and matching configuration, then stop its Orthanc container and move its initialized storage into a separate quarantine volume. This preserves the target's existing data and its generated configuration; a never-started container has no effective configuration and cannot run these commands yet.

Run the following deliberately in the recovery project. Replace `myproject` and the archive path. The quarantine volume is retained after recovery:

```bash
set -euo pipefail
project=myproject
container="ddev-${project}-orthanc"
image=$(docker inspect --format '{{.Config.Image}}' "$container")
quarantine="ddev-${project}-orthanc-before-restore-$(date +%Y%m%d%H%M%S)"
docker stop "$container"
docker run --rm --network none --volumes-from "$container" \
  --mount "type=volume,source=$quarantine,target=/quarantine" \
  --entrypoint python3 "$image" -c '
from pathlib import Path
import shutil
source, target = Path("/var/lib/orthanc/db"), Path("/quarantine")
assert not any(target.iterdir()), "Quarantine must be empty"
for item in source.iterdir():
    shutil.move(str(item), target / item.name)
print("Initialized storage preserved in quarantine")
'
ddev orthanc restore "/private/path/archive.tar.gz" --yes
ddev restart
ddev orthanc doctor
```

Retain the quarantine and backup until restored instance counts and retrieval are verified. If a move fails, keep Orthanc stopped and inspect both volumes; no command deletes the preserved files. There is no force-overwrite or automatic deletion mode.

Restore overwrites only known JSON, Lua and environment files present in the archive. Files absent from it are preserved; if an existing local override differs, move it aside deliberately before restoring. Runtime Compose configuration must match the source. After a successful restore, run `ddev restart` to recreate the container with restored environment settings, then check `doctor`, instance counts and retrieval. The effective configuration in the archive is evidence only and is not installed as an extra config file.

## Local verification and CI

```bash
python3 -m unittest discover -s tests/unit -v
bash -n commands/host/orthanc
shellcheck commands/host/orthanc
bats tests/test.bats
```

Integration requires DDEV, Docker, jq, curl, Bats and host DCMTK (`echoscu`/`storescu`). It uses unique temporary projects and port 14242 by default; override with `ORTHANC_TEST_DICOM_PORT`. It installs current source from a tracked-path snapshot, checks authentication, deterministic seed, REST retrieval, C-ECHO/C-STORE, recreated-container persistence, owned-file preservation, removal/reinstallation, plugin toggles and a stopped-volume backup/restore round trip. Release testing is skipped unless `ORTHANC_TEST_RELEASE=1`; enable it only after a compatible release is published.

Persistent manual acceptance uses repository-root `test_project/`, excluded from Git and release archives. To make a source snapshot without recursively including it:

```bash
snapshot=$(mktemp -d)
git ls-files -z | tar --null -T - -cf - | tar -C "$snapshot" -xf -
cd test_project
ddev add-on get "$snapshot"
ddev restart
```

CI uses the v2 add-on action with stable/HEAD DDEV on amd64/arm64, read-only repository permissions, static/unit checks and source integration. On failure it retains version/container diagnostics. Workflow configuration is not proof of a successful remote run: historical issues #1 and #4 remain unresolved until published changes pass active CI.

Maintained by [@madebydaniz](https://github.com/madebydaniz). DDEV configuration references: [add-on lifecycle](https://docs.ddev.com/en/stable/users/extend/creating-add-ons/) and [custom services](https://docs.ddev.com/en/stable/users/extend/custom-docker-services/).
