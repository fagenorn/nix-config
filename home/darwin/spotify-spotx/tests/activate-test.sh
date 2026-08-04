#!/usr/bin/env bash

set -uo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
helper=${HELPER_UNDER_TEST:-"${script_dir}/../activate.sh"}
test_root=$(mktemp -d "${TMPDIR:-/tmp}/spotify-spotx-tests.XXXXXXXX")
trap 'rm -rf "${test_root}"' EXIT

tests_run=0
tests_failed=0

pass() {
  tests_run=$((tests_run + 1))
  printf 'ok %d - %s\n' "${tests_run}" "$1"
}

fail() {
  tests_run=$((tests_run + 1))
  tests_failed=$((tests_failed + 1))
  printf 'not ok %d - %s\n' "${tests_run}" "$1"
  if [[ -f "${case_dir:-}/stderr" ]]; then
    sed 's/^/  stderr: /' "${case_dir}/stderr"
  fi
}

assert_success() {
  local name=$1
  shift
  if "$@"; then
    pass "${name}"
  else
    fail "${name}"
  fi
}

assert_failure() {
  local name=$1
  shift
  if "$@"; then
    fail "${name}"
  else
    pass "${name}"
  fi
}

write_fake_command() {
  local name=$1
  local body=$2
  printf '#!/usr/bin/env bash\n%s\n' "${body}" > "${fake_bin}/${name}"
  chmod +x "${fake_bin}/${name}"
}

write_fake_spotx() {
  local source_dir=$1
  local build_version=$2
  mkdir -p "${source_dir}"
  {
    printf '#!/usr/bin/env bash\n'
    printf 'buildVer="%s.gabcdef"\n' "${build_version}"
    printf '%s\n' \
      'set -u' \
      'printf "SPOTX_BUILD_MODE=%s\\n" "${SPOTX_BUILD_MODE:-}" >> "${SPOTX_LOG}"' \
      'printf "argv:" >> "${SPOTX_LOG}"' \
      'printf " <%s>" "$@" >> "${SPOTX_LOG}"' \
      'printf "\\n" >> "${SPOTX_LOG}"' \
      '[[ "${FAKE_SPOTX_FAIL:-0}" != 1 ]] || exit 17' \
      'install_path=' \
      'while (($#)); do' \
      '  if [[ "$1" == -P ]]; then install_path=$2; shift 2; else shift; fi' \
      'done' \
      '[[ -n "${install_path}" ]] || exit 18' \
      'app="${install_path}/Spotify.app"' \
      'mkdir -p "${app}/Contents/MacOS" "${app}/Contents/Resources/Apps"' \
      ': > "${app}/Contents/MacOS/Spotify.bak"' \
      ': > "${app}/Contents/Resources/Apps/xpui.bak"'
  } > "${source_dir}/spotx.sh"
  chmod +x "${source_dir}/spotx.sh"
}

setup_case() {
  local name=$1
  local spotify_version=${2:-1.2.3.4}
  local build_version=${3:-1.2.3.4}

  case_dir="${test_root}/${name}"
  app_parent="${case_dir}/Applications"
  app="${app_parent}/Spotify.app"
  state_dir="${case_dir}/state"
  fake_bin="${case_dir}/bin"
  spotx_source="${case_dir}/spotx-source"
  spotx_script="${spotx_source}/spotx.sh"
  spotx_log="${case_dir}/spotx.log"
  command_log="${case_dir}/commands.log"

  mkdir -p \
    "${app}/Contents/MacOS" \
    "${app}/Contents/Resources/Apps" \
    "${fake_bin}"
  : > "${app}/Contents/MacOS/Spotify"
  : > "${app}/Contents/Resources/Apps/xpui.spa"
  : > "${spotx_log}"
  : > "${command_log}"

  write_fake_spotx "${spotx_source}" "${build_version}"
  write_fake_command defaults 'printf "%s\\n" "${FAKE_SPOTIFY_VERSION}"'
  write_fake_command pkill 'printf "pkill:" >> "${COMMAND_LOG}"; printf " <%s>" "$@" >> "${COMMAND_LOG}"; printf "\\n" >> "${COMMAND_LOG}"; exit 1'
  write_fake_command codesign 'printf "codesign:" >> "${COMMAND_LOG}"; printf " <%s>" "$@" >> "${COMMAND_LOG}"; printf "\\n" >> "${COMMAND_LOG}"; [[ "$1" != --verify || "${FAKE_CODESIGN_FAIL:-0}" != 1 ]]'

  export FAKE_SPOTIFY_VERSION=${spotify_version}
  export SPOTX_LOG=${spotx_log}
  export COMMAND_LOG=${command_log}
  unset FAKE_SPOTX_FAIL FAKE_CODESIGN_FAIL
}

run_helper() {
  DEFAULTS_BIN="${fake_bin}/defaults" \
    PKILL_BIN="${fake_bin}/pkill" \
    CODESIGN_BIN="${fake_bin}/codesign" \
    bash "${helper}" \
      "${spotx_script}" \
      "${app}" \
      "${state_dir}" \
      "$@" \
      > "${case_dir}/stdout" 2> "${case_dir}/stderr"
}

test_missing_app_fails() {
  setup_case missing-app
  rm -rf "${app}"
  assert_failure "missing app fails" run_helper --blockupdates --hide
}

test_newer_version_skips() {
  setup_case newer-version 1.2.3.5 1.2.3.4
  assert_success "newer unsupported Spotify skips successfully" run_helper --blockupdates --hide
  assert_success "newer unsupported Spotify does not invoke SpotX" test ! -s "${spotx_log}"
  assert_success "newer unsupported Spotify does not write state" test ! -e "${state_dir}/state"
}

test_clean_app_patches() {
  setup_case clean-app
  assert_success "compatible clean app patches successfully" run_helper --blockupdates --hide
  assert_success "clean patch passes the expected SpotX arguments" \
    grep -Fxq 'argv: <--blockupdates> <--hide> <-P> '"<${app_parent}>" "${spotx_log}"
  assert_success "clean patch enables SpotX build mode" \
    grep -Fxq 'SPOTX_BUILD_MODE=1' "${spotx_log}"
  assert_success "clean patch creates both backups" \
    test -f "${app}/Contents/MacOS/Spotify.bak" -a \
      -f "${app}/Contents/Resources/Apps/xpui.bak"
  expected_state=$(printf 'spotify_version=1.2.3.4\nspotx_store_path=%s\narguments=--blockupdates --hide\n' "${spotx_source}")
  assert_success "clean patch writes the successful state" \
    test "$(cat "${state_dir}/state")" = "${expected_state%$'\n'}"
  assert_success "clean patch verifies the strict code signature" \
    grep -Fxq 'codesign: <--verify> <--deep> <--strict> '"<${app}>" "${command_log}"
}

test_matching_state_is_noop() {
  setup_case matching-state
  if ! run_helper --blockupdates --hide; then
    fail "matching-state fixture patches initially"
    return
  fi
  touch -t 200001010000 "${state_dir}/state"
  marker_mtime=$(perl -e 'print((stat shift)[9])' "${state_dir}/state")
  : > "${spotx_log}"
  : > "${command_log}"

  assert_success "matching backups and state are a no-op" run_helper --blockupdates --hide
  assert_success "matching state does not invoke SpotX" test ! -s "${spotx_log}"
  assert_success "matching state does not stop Spotify or verify signing" test ! -s "${command_log}"
  assert_success "matching state marker is not rewritten" \
    test "$(perl -e 'print((stat shift)[9])' "${state_dir}/state")" = "${marker_mtime}"
}

test_changed_source_forces_repatch() {
  setup_case changed-source
  if ! run_helper --blockupdates --hide; then
    fail "changed-source fixture patches initially"
    return
  fi
  second_source="${case_dir}/second-spotx-source"
  write_fake_spotx "${second_source}" 1.2.3.4
  spotx_source=${second_source}
  spotx_script="${second_source}/spotx.sh"
  : > "${spotx_log}"

  assert_success "changed SpotX source repatches successfully" run_helper --blockupdates --hide
  assert_success "changed SpotX source adds force" \
    grep -Fxq 'argv: <--blockupdates> <--hide> <--force> <-P> '"<${app_parent}>" "${spotx_log}"
}

test_changed_arguments_force_repatch() {
  setup_case changed-arguments
  if ! run_helper --blockupdates --hide; then
    fail "changed-arguments fixture patches initially"
    return
  fi
  : > "${spotx_log}"

  assert_success "changed arguments repatch successfully" run_helper --blockupdates
  assert_success "changed arguments add force" \
    grep -Fxq 'argv: <--blockupdates> <--force> <-P> '"<${app_parent}>" "${spotx_log}"
}

test_partial_backups_fail_without_state_change() {
  setup_case partial-backups
  mkdir -p "${state_dir}"
  printf 'previous-state\n' > "${state_dir}/state"
  : > "${app}/Contents/MacOS/Spotify.bak"

  assert_failure "partial backups fail" run_helper --blockupdates --hide
  assert_success "partial backups do not invoke SpotX" test ! -s "${spotx_log}"
  assert_success "partial backups preserve state" \
    grep -Fxq 'previous-state' "${state_dir}/state"
}

test_patch_failure_does_not_write_state() {
  setup_case patch-failure
  export FAKE_SPOTX_FAIL=1

  assert_failure "SpotX patch failure propagates" run_helper --blockupdates --hide
  assert_success "SpotX patch failure does not write state" test ! -e "${state_dir}/state"
}

test_signing_failure_does_not_write_state() {
  setup_case signing-failure
  export FAKE_CODESIGN_FAIL=1

  assert_failure "strict signing failure propagates" run_helper --blockupdates --hide
  assert_success "strict signing failure does not write state" test ! -e "${state_dir}/state"
}

printf 'TAP version 13\n'
test_missing_app_fails
test_newer_version_skips
test_clean_app_patches
test_matching_state_is_noop
test_changed_source_forces_repatch
test_changed_arguments_force_repatch
test_partial_backups_fail_without_state_change
test_patch_failure_does_not_write_state
test_signing_failure_does_not_write_state

printf '1..%d\n' "${tests_run}"

if ((tests_failed)); then
  printf '%d of %d assertions failed\n' "${tests_failed}" "${tests_run}" >&2
  exit 1
fi
