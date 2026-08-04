#!/usr/bin/env bash

set -euo pipefail

die() {
  printf 'spotify-spotx: error: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf 'spotify-spotx: warning: %s\n' "$*" >&2
}

if (($# < 4)); then
  die "usage: activate.sh SPOTX_SCRIPT SPOTIFY_APP STATE_DIR SPOTX_ARG..."
fi

spotx_script=$1
spotify_app=$2
state_dir=$3
shift 3
spotx_args=("$@")

bash_bin=${BASH_BIN:-${BASH}}
perl_bin=${PERL_BIN:-perl}
defaults_bin=${DEFAULTS_BIN:-/usr/bin/defaults}
pkill_bin=${PKILL_BIN:-/usr/bin/pkill}
codesign_bin=${CODESIGN_BIN:-/usr/bin/codesign}

[[ -r "${spotx_script}" ]] || die "SpotX script is not readable: ${spotx_script}"
[[ -d "${spotify_app}" ]] || die "Spotify app is missing: ${spotify_app}. Reinstall the Homebrew spotify cask and activate again."

spotify_raw=$(
  "${defaults_bin}" read \
    "${spotify_app}/Contents/Info.plist" \
    CFBundleShortVersionString
) || die "could not read Spotify's CFBundleShortVersionString"

spotify_version=$(
  "${perl_bin}" -e '
    my $value = shift;
    if ($value =~ /^\s*"?(\d+(?:\.\d+){3})(?:\.g[0-9a-f]+)?"?\s*$/i) {
      print $1;
      exit 0;
    }
    exit 1;
  ' "${spotify_raw}"
) || die "could not parse Spotify version: ${spotify_raw}"

spotx_version=$(
  "${perl_bin}" -ne '
    if (/^\s*buildVer="(\d+(?:\.\d+){3})(?:\.g[0-9a-f]+)?"\s*$/i) {
      print "$1\n";
      exit 0;
    }
  ' "${spotx_script}"
)
[[ -n "${spotx_version}" ]] || die "could not parse buildVer from ${spotx_script}"

version_is_newer() {
  "${perl_bin}" -e '
    my @left = split /\./, $ARGV[0];
    my @right = split /\./, $ARGV[1];
    for my $index (0 .. 3) {
      exit 0 if $left[$index] > $right[$index];
      exit 1 if $left[$index] < $right[$index];
    }
    exit 1;
  ' "$1" "$2"
}

if version_is_newer "${spotify_version}" "${spotx_version}"; then
  warn "Spotify ${spotify_version} is newer than SpotX support ${spotx_version}; leaving Spotify unpatched until the pinned SpotX input advances."
  exit 0
fi

app_backup="${spotify_app}/Contents/MacOS/Spotify.bak"
xpui_backup="${spotify_app}/Contents/Resources/Apps/xpui.bak"
state_file="${state_dir}/state"
spotx_store_path=${spotx_script%/*}
arguments=${spotx_args[*]}
expected_state=$(printf \
  'spotify_version=%s\nspotx_store_path=%s\narguments=%s' \
  "${spotify_version}" \
  "${spotx_store_path}" \
  "${arguments}")

app_backup_exists=0
xpui_backup_exists=0
[[ -f "${app_backup}" ]] && app_backup_exists=1
[[ -f "${xpui_backup}" ]] && xpui_backup_exists=1

if ((app_backup_exists != xpui_backup_exists)); then
  die "only one SpotX backup exists. Reinstall the Homebrew spotify cask before activating again; the app bundle was not modified."
fi

force=0
if ((app_backup_exists)); then
  current_state=
  [[ -f "${state_file}" ]] && current_state=$(<"${state_file}")
  if [[ "${current_state}" == "${expected_state}" ]]; then
    exit 0
  fi
  force=1
fi

# SPOTX_BUILD_MODE prevents SpotX from reaching the network or killing Spotify.
# Home Manager owns the process stop so it happens only when patching is needed.
"${pkill_bin}" -x Spotify >/dev/null 2>&1 || true

command=("${spotx_script}" "${spotx_args[@]}")
((force == 0)) || command+=(--force)
command+=(-P "${spotify_app%/Spotify.app}")

SPOTX_BUILD_MODE=1 "${bash_bin}" "${command[@]}"

[[ -f "${app_backup}" && -f "${xpui_backup}" ]] || \
  die "SpotX returned successfully without creating both expected backups"

"${codesign_bin}" --verify --deep --strict "${spotify_app}" || \
  die "Spotify's strict code-signature verification failed"

/bin/mkdir -p "${state_dir}"
state_tmp=$(/usr/bin/mktemp "${state_dir}/state.XXXXXXXX")
cleanup_state_tmp() {
  /bin/rm -f "${state_tmp}"
}
trap cleanup_state_tmp EXIT

printf '%s\n' "${expected_state}" > "${state_tmp}"
/bin/chmod 600 "${state_tmp}"
/bin/mv -f "${state_tmp}" "${state_file}"
trap - EXIT
