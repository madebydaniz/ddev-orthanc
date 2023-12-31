setup() {
  set -eu -o pipefail
  export DIR="$( cd "$( dirname "$BATS_TEST_FILENAME" )" >/dev/null 2>&1 && pwd )/.."
  export TESTDIR=~/tmp/test-orthanc
  mkdir -p $TESTDIR
  export PROJNAME=test-orthanc
  export DDEV_NON_INTERACTIVE=true
  ddev delete -Oy ${PROJNAME} >/dev/null 2>&1 || true
  cd "${TESTDIR}"
  ddev config --project-name=${PROJNAME}
  ddev start -y >/dev/null
}


teardown() {
  set -eu -o pipefail
  cd ${TESTDIR} || ( printf "unable to cd to ${TESTDIR}\n" && exit 1 )
  ddev delete -Oy ${PROJNAME} >/dev/null 2>&1
  [ "${TESTDIR}" != "" ] && rm -rf ${TESTDIR}
}

@test "install from directory" {
  set -eu -o pipefail
  cd ${TESTDIR}
  echo "# ddev get ${DIR} with project ${PROJNAME} in ${TESTDIR} ($(pwd))" >&3
  ddev get ${DIR}
  ddev restart >/dev/null
  URL=$(ddev describe -j ${PROJNAME} | jq -r .raw.httpurl)
  curl -u "orthanc:orthanc" -s --fail ${URL}:8042
}

@test "install from release" {
  set -eu -o pipefail
  cd ${TESTDIR} || ( printf "unable to cd to ${TESTDIR}\n" && exit 1 )
  echo "# ddev get madebydaniz/ddev-orthanc with project ${PROJNAME} in ${TESTDIR} ($(pwd))" >&3
  ddev get madebydaniz/ddev-orthanc
  ddev restart >/dev/null
  URL=$(ddev describe -j ${PROJNAME} | jq -r .raw.httpurl)
  curl -u "orthanc:orthanc" -s --fail ${URL}:8042
}

