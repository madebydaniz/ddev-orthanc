# Changelog

## Unreleased

- Require DDEV 1.25.4 and pin Orthanc image 26.9.1.
- Persist SQLite and DICOM storage in a project volume; preserve user configuration on upgrade.
- Route HTTP/HTTPS, bind configurable DICOM ports to localhost, enable authenticated readiness and Explorer 2.
- Add URL, doctor, deterministic synthetic seed, private stopped-storage backup and validated empty-volume restore commands.
- Add source lifecycle and archive security tests, amd64/arm64 stable/HEAD CI and development documentation.
- Allow compatible OrthancTeam image overrides and custom plugin mounts while retaining audited backup restrictions.
- Run doctor C-ECHO through the native Orthanc API and test exact tags on published-release events.
- Keep legacy storage migration explicit and release tests opt-in until a compatible release is published.
