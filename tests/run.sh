#!/usr/bin/env bash
# Every check this repository has: shell syntax, shellcheck where it is
# installed, Python syntax, the unit tests, and the D-Bus tests against a fake
# KDE Connect rather than the phone.
#
#   tests/run.sh          all of it
#   tests/run.sh unit     the unit tests alone
#   tests/run.sh dbus     the D-Bus tests alone
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fail=0
want=${1-all}
run() { printf '\n== %s\n' "$1"; shift; "$@" || fail=1; }

if [[ $want == all ]]; then
  for script in phonelink install.sh setup.sh tests/run.sh; do
    [[ -f $script ]] && run "bash -n $script" bash -n "$script"
  done
  if command -v shellcheck >/dev/null; then
    run "shellcheck" shellcheck -S warning phonelink install.sh setup.sh tests/run.sh
  else
    printf '\n== shellcheck: not installed, skipped\n'
  fi
  if command -v ruff >/dev/null; then
    run "ruff" ruff check lib tests integration
  else
    printf '\n== ruff: not installed, skipped\n'
  fi
  run "python syntax" python3 -m compileall -q lib tests
fi

if [[ $want == all || $want == unit ]]; then
  # The D-Bus tests skip themselves here; they need the private bus below.
  run "unit tests" env PYTHONPATH=lib \
    python3 -m unittest discover -s tests -p 'test_*.py' -v
fi

if [[ $want == all || $want == dbus ]]; then
  if command -v dbus-run-session >/dev/null; then
    # A private bus, and an empty XDG_DATA_DIRS with it: on the session bus the
    # fake would fight the real daemon, and without this, asking for
    # org.kde.kdeconnect would simply start the real one instead.
    empty=$(mktemp -d)
    trap 'rm -rf "$empty"' EXIT
    run "D-Bus tests" env XDG_DATA_DIRS="$empty" PHONELINK_TEST_BUS=1 PYTHONPATH=lib \
      dbus-run-session -- python3 -m unittest discover -s tests -p 'test_dbus_*.py' -v
  else
    printf '\n== D-Bus tests: dbus-run-session not installed, skipped\n'
  fi
fi

printf '\n'
if ((fail)); then
  echo "FAILED"
else
  echo "all checks passed"
fi
exit "$fail"
