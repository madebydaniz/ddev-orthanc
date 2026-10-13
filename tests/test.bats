setup() {
  set -euo pipefail
  DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  TESTDIR="$(mktemp -d "${TMPDIR:-/tmp}/ddev-orthanc-test.XXXXXX")"
  PROJNAME="orthanc-test-$(date +%s)-$RANDOM"
  export DIR TESTDIR PROJNAME
  export DDEV_NONINTERACTIVE=true
  export RESTORE_NAME="${PROJNAME}-restore"
  export RESTORE_VOLUME="${RESTORE_NAME}-data"
  export ORTHANC_DICOM_PORT="${ORTHANC_TEST_DICOM_PORT:-14242}"
  mkdir -p "$TESTDIR/source"
  # Use tracked paths, with current working contents, to exclude local acceptance data.
  git -C "$DIR" ls-files -z | tar -C "$DIR" --null -T - -cf - | tar -C "$TESTDIR/source" -xf -
  # New tracked candidate files are explicitly copied until the first commit.
  for file in .env.orthanc orthanc/.gitignore orthanc/tools/orthanc.py; do
    mkdir -p "$TESTDIR/source/$(dirname "$file")"
    cp "$DIR/$file" "$TESTDIR/source/$file"
  done
  cd "$TESTDIR"
  ddev config --project-name="$PROJNAME" --project-type=php
  mkdir -p .ddev
  printf 'ORTHANC_DICOM_PORT=%s\n' "$ORTHANC_DICOM_PORT" > .ddev/.env.orthanc.local
}

teardown() {
  set +e
  cd "$TESTDIR" || return
  if [[ "${BATS_TEST_COMPLETED:-}" != 1 ]]; then
    # Tail only; never dump effective config, environment or API bodies.
    ddev logs -s orthanc --tail=40 >&3
    docker logs --tail=40 "ddev-${RESTORE_NAME}-orthanc" >&3 2>&3 || true
  fi
  docker rm -f "ddev-${RESTORE_NAME}-orthanc" >/dev/null 2>&1
  docker volume rm "$RESTORE_VOLUME" >/dev/null 2>&1
  ddev delete -Oy "$PROJNAME" >/dev/null 2>&1
  docker volume rm "ddev-${PROJNAME}-orthanc-data" >/dev/null 2>&1
  [[ "$TESTDIR" == *"/ddev-orthanc-test."* ]] && rm -rf "$TESTDIR"
}

api() {
  ddev exec -s orthanc python3 -c "import runpy,json; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); print(json.dumps(m['request']('$1')))"
}

@test "source lifecycle: authentication, DICOM, persistence, configuration and backup restore" {
  ddev add-on get "$TESTDIR/source"
  ddev start >/dev/null
  run ddev orthanc doctor
  [ "$status" -eq 0 ]
  [[ "$output" == *"authenticated API"* ]]
  [[ "$output" == *"DICOM C-ECHO: passed"* ]]
  url=$(ddev orthanc url)
  [[ "$url" == https://*:8043 ]]
  run curl -s -o /dev/null -w '%{http_code}' "$url/system"
  [ "$status" -eq 0 ]
  [ "$output" = 401 ]
  first=$(ddev orthanc seed | tail -n 1)
  second=$(ddev orthanc seed | tail -n 1)
  [ "$(printf '%s' "$first" | jq -r .ID)" = "$(printf '%s' "$second" | jq -r .ID)" ]
  [ "$(printf '%s' "$second" | jq -r .Status)" = AlreadyStored ]
  instance=$(printf '%s' "$first" | jq -r .ID)
  run api "/instances/$instance"
  [ "$status" -eq 0 ]
  [[ "$output" == *"$instance"* ]]
  ddev exec -s orthanc python3 -c "import runpy; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); open('/tmp/synthetic.dcm','wb').write(m['seed_dicom']())"
  if command -v echoscu >/dev/null && command -v storescu >/dev/null; then
    echoscu -aec ORTHANC 127.0.0.1 "$ORTHANC_DICOM_PORT"
    docker cp "ddev-${PROJNAME}-orthanc:/tmp/synthetic.dcm" "$TESTDIR/synthetic.dcm"
    ddev exec -s orthanc python3 -c "import runpy; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); m['request']('/instances/$instance', method='DELETE')"
    storescu -aec ORTHANC 127.0.0.1 "$ORTHANC_DICOM_PORT" "$TESTDIR/synthetic.dcm"
    run api "/instances/$instance"
    [ "$status" -eq 0 ]
  else
    echo 'DICOM test requires host DCMTK echoscu and storescu.' >&3
    return 1
  fi
  docker rm -f "ddev-${PROJNAME}-orthanc" >/dev/null
  ddev start >/dev/null
  run api "/instances/$instance"
  [ "$status" -eq 0 ]

  # Marker removal transfers ownership to the user; repeated installation preserves it.
  sed '/ddev-generated/d' .ddev/orthanc/config/orthanc.json > "$TESTDIR/custom.json"
  mv "$TESTDIR/custom.json" .ddev/orthanc/config/orthanc.json
  printf '\n' >> .ddev/orthanc/config/orthanc.json
  cp .ddev/orthanc/config/orthanc.json "$TESTDIR/expected.json"
  ddev add-on get "$TESTDIR/source"
  cmp .ddev/orthanc/config/orthanc.json "$TESTDIR/expected.json"
  printf '\nORTHANC__REGISTERED_USERS={"developer":"synthetic-test-password"}\n' >> .ddev/.env.orthanc.local
  ddev restart >/dev/null
  run curl -s -u orthanc:orthanc -o /dev/null -w '%{http_code}' "$url/system"
  [ "$status" -eq 0 ]
  [ "$output" = 401 ]
  run ddev orthanc doctor
  [ "$status" -eq 0 ]
  ddev orthanc backup "$TESTDIR/backup with spaces.tar.gz"
  [ -f "$TESTDIR/backup with spaces.tar.gz" ]
  run ddev orthanc backup "$TESTDIR/backup with spaces.tar.gz"
  [ "$status" -ne 0 ]
  run ddev orthanc restore "$TESTDIR/backup with spaces.tar.gz" --yes
  [ "$status" -ne 0 ]
  [ "$(docker inspect -f '{{.State.Running}}' "ddev-${PROJNAME}-orthanc")" = true ]

  # A new stopped target with a fresh volume has never initialized a database.
  docker create --name "ddev-${RESTORE_NAME}-orthanc" \
    --mount "type=volume,source=$RESTORE_VOLUME,target=/var/lib/orthanc/db" \
    --mount "type=bind,source=$TESTDIR/.ddev,target=/mnt/ddev_config" \
    --mount "type=bind,source=$TESTDIR/.ddev/orthanc/config,target=/etc/orthanc,readonly" \
    --mount "type=bind,source=$TESTDIR/.ddev/orthanc/scripts,target=/etc/share/orthanc/scripts,readonly" \
    --env-file "$TESTDIR/.ddev/.env.orthanc" \
    --env-file "$TESTDIR/.ddev/.env.orthanc.local" orthancteam/orthanc:26.9.1 >/dev/null
  # Preserve container ownership so Linux sticky-directory protections permit startup to rewrite it.
  docker cp "ddev-${PROJNAME}-orthanc:/tmp/orthanc.json" - | docker cp -a - "ddev-${RESTORE_NAME}-orthanc:/tmp/"
  DDEV_SITENAME="$RESTORE_NAME" bash "$DIR/commands/host/orthanc" restore "$TESTDIR/backup with spaces.tar.gz" --yes
  docker start "ddev-${RESTORE_NAME}-orthanc" >/dev/null
  for _attempt in $(seq 1 30); do
    if docker exec "ddev-${RESTORE_NAME}-orthanc" python3 /mnt/ddev_config/orthanc/tools/orthanc.py ready; then break; fi
    [ "$(docker inspect -f '{{.State.Running}}' "ddev-${RESTORE_NAME}-orthanc")" = true ] || return 1
    sleep 1
  done
  docker exec "ddev-${RESTORE_NAME}-orthanc" python3 -c "import runpy; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); assert m['request']('/instances/$instance')['ID']=='$instance'"
  docker rm -f "ddev-${RESTORE_NAME}-orthanc" >/dev/null
  ddev add-on remove orthanc
  [ -f .ddev/orthanc/config/orthanc.json ]
  ddev add-on get "$TESTDIR/source"
  ddev restart >/dev/null
  run api "/instances/$instance"
  [ "$status" -eq 0 ]
  printf '\nDICOM_WEB_PLUGIN_ENABLED=true\nOHIF_PLUGIN_ENABLED=true\nSTONE_WEB_VIEWER_PLUGIN_ENABLED=true\n' >> .ddev/.env.orthanc.local
  ddev restart >/dev/null
  plugins=$(api /plugins)
  [[ "$plugins" == *"dicom-web"* ]]
  [[ "$plugins" == *"ohif"* ]]
  [[ "$plugins" == *"stone-webviewer"* ]]
  ddev exec -s orthanc python3 -c "import runpy; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); assert b'<html' in m['request']('/stone-webviewer/index.html', raw=True).lower()"
  studies=$(api /dicom-web/studies)
  printf '%s' "$studies" | jq -e '.[] | select(.["0020000D"].Value[0] == "1.2.826.0.1.3680043.10.543.20261013.1.1")' >/dev/null
  ddev exec -s orthanc python3 -c "import runpy; m=runpy.run_path('/mnt/ddev_config/orthanc/tools/orthanc.py'); uid=m['SEED_UID']; payload=m['request']('/dicom-web/studies/'+uid+'.1/series/'+uid+'.2/instances/'+uid, raw=True); assert b'DICM' in payload; assert bytes((0,85,170,255)) in payload"
}

@test "release lifecycle is opt-in until a compatible release is published" {
  [[ "${ORTHANC_TEST_RELEASE:-}" == 1 ]] || skip 'Set ORTHANC_TEST_RELEASE=1 after publishing the maintained release.'
  if [[ -n "${ORTHANC_TEST_RELEASE_VERSION:-}" ]]; then
    ddev add-on get madebydaniz/ddev-orthanc --version="$ORTHANC_TEST_RELEASE_VERSION"
  else
    ddev add-on get madebydaniz/ddev-orthanc
  fi
  ddev start >/dev/null
  ddev orthanc doctor
  ddev orthanc seed
}

