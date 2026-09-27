#!/usr/bin/env bash
# Make Playwright's bundled Chromium runnable without root, and print the
# LD_LIBRARY_PATH that does it.
#
# A production operator runs `playwright install-deps` as root, or installs
# libnss3/libnspr4/libasound2 through the distribution's package manager, and
# needs none of this. The e2e suite also runs on unprivileged build machines and
# in containers, where "apt-get install" is not available. There, Chromium dies
# at launch with
#
#   error while loading shared libraries: libnspr4.so: cannot open shared
#   object file: No such file or directory
#
# and every test fails for that reason alone, which looks exactly like an
# application failure. This fetches only the three packages Chromium needs,
# unpacks them into a repository-local prefix, and prints the variable to export.
# Nothing is installed system-wide and no root is required.
#
# Output is the library path on stdout, so the caller is simply:
#
#   export LD_LIBRARY_PATH="$("$(dirname -- "${BASH_SOURCE[0]}")/browser-libs.sh")"
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

PREFIX="${NACHTLABS_BROWSER_LIBS:-$NACHTLABS_ROOT/.browser-libs}"

# libnss3 unpacks under a distribution-dependent multiarch path, so resolve the
# directory from the file itself rather than assuming one. dirname "" is ".", so
# an absent file has to be detected before deriving anything from it.
libnss_dir() {
  local found
  found="$(find "$PREFIX" -name 'libnss3.so' -print -quit 2>/dev/null || true)"
  [[ -n "$found" ]] && dirname "$found"
}

# Playwright's own headless shell is the thing that has to launch; check that
# rather than guessing, so this stays correct across Playwright upgrades.
SHELL_BIN="$(ls -d "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null | head -1 || true)"

missing_libs() {
  local binary="$1"
  ldd "$binary" 2>/dev/null | awk '/not found/ {print $1}' | sort -u
}

# Nothing to do on a host that already resolves every library, which is the
# normal installed-deployment case.
if [[ -n "$SHELL_BIN" ]]; then
  if [[ -z "$(missing_libs "$SHELL_BIN")" ]]; then
    printf '%s\n' "${LD_LIBRARY_PATH:-}"
    exit 0
  fi
fi

LIBDIR="$(libnss_dir || true)"
if [[ -z "$LIBDIR" ]]; then
  printf 'Fetching the shared libraries Chromium needs into %s\n' "$PREFIX" >&2
  rm -rf "$PREFIX"
  mkdir -p "$PREFIX/debs"
  # libasound2 is a time_t transitional package on 24.04 and later; the older
  # name still exists on earlier releases, so try both rather than guessing the
  # distribution version.
  (
    cd "$PREFIX/debs"
    apt-get download libnspr4 libnss3 libasound2t64 ||
      apt-get download libnspr4 libnss3 libasound2
  ) >&2
  for package in "$PREFIX"/debs/*.deb; do
    dpkg-deb -x "$package" "$PREFIX/root"
  done
  LIBDIR="$(libnss_dir || true)"
  [[ -n "$LIBDIR" ]] || {
    printf 'Could not locate the unpacked libraries under %s\n' "$PREFIX" >&2
    exit 1
  }
  rm -rf "$PREFIX/debs"
fi

if [[ -n "$SHELL_BIN" ]]; then
  remaining="$(LD_LIBRARY_PATH="$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" missing_libs "$SHELL_BIN")"
  if [[ -n "$remaining" ]]; then
    printf 'Chromium still cannot resolve: %s\n' "$(echo "$remaining" | tr '\n' ' ')" >&2
    printf 'Install them as root, or set NACHTLABS_BROWSER_LIBS to a prefix that has them.\n' >&2
    exit 1
  fi
  printf 'Chromium can now launch with %s\n' "$LIBDIR" >&2
fi

printf '%s\n' "$LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
