#!/bin/sh
# Exercises install.sh's SwiftBar detection in isolation.
#
# Regression guard: the first version relied on `mdfind -name "SwiftBar.app"`,
# which returns nothing even when the app is installed and indexed. On a Mac
# with SwiftBar somewhere other than /Applications or ~/Applications that made
# the installer offer to install it a second time.
#
# Run:  sh tests/test_install_detection.sh

set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0

check() { # check <name> <expected> <actual>
    if [ "$2" = "$3" ]; then
        printf '  ok    %s\n' "$1"; PASS=$((PASS + 1))
    else
        printf '  FAIL  %s\n        expected: %s\n        actual:   %s\n' \
            "$1" "$2" "$3"; FAIL=$((FAIL + 1))
    fi
}

# Pull the function under test straight out of the installer.
sed -n '/^find_swiftbar()/,/^}/p' "$REPO/install.sh" > "$WORK/fn.sh"
[ -s "$WORK/fn.sh" ] || { echo "could not extract find_swiftbar"; exit 1; }

# Stubs for the external lookups, switched on per scenario.
mkdir -p "$WORK/bin"
for tool in ps osascript mdfind; do
    VAR="STUB_$(echo "$tool" | tr 'a-z' 'A-Z')"
    cat > "$WORK/bin/$tool" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >> "$WORK/$tool.args"
[ -n "\${$VAR:-}" ] && printf '%s\n' "\$$VAR"
exit 0
EOF
    chmod +x "$WORK/bin/$tool"
done

run_case() { # run_case <home> -> prints found path or empty
    HOME="$1" PATH="$WORK/bin:$PATH" sh -c '
        set -eu
        . "$1/fn.sh"
        find_swiftbar || true
    ' _ "$WORK"
}

echo "find_swiftbar:"

# 1. Present in ~/Applications -- the plain directory hit.
H1="$WORK/home1"; mkdir -p "$H1/Applications/SwiftBar.app"
check "finds it in ~/Applications" \
    "$H1/Applications/SwiftBar.app" "$(run_case "$H1")"

# 2. Installed somewhere unusual, but running. This is the case that used to
#    fall through to a second install.
H2="$WORK/home2"; mkdir -p "$H2"
ODD="$WORK/Odd Place/SwiftBar.app"; mkdir -p "$ODD/Contents/MacOS"
check "finds a running instance in an unusual folder" "$ODD" \
    "$(STUB_PS="$ODD/Contents/MacOS/SwiftBar" run_case "$H2")"

# 3. Not running, but registered with LaunchServices (trailing slash).
check "finds it via LaunchServices" "$ODD" \
    "$(STUB_OSASCRIPT="$ODD/" run_case "$H2")"

# 4. Only Spotlight knows, queried by bundle id rather than filename. The
#    query text matters: `mdfind -name "SwiftBar.app"` finds nothing even when
#    the app is installed, which is what made this fall through originally.
rm -f "$WORK/mdfind.args"
check "finds it via Spotlight" "$ODD" \
    "$(STUB_MDFIND="$ODD" run_case "$H2")"
if grep -q "kMDItemCFBundleIdentifier" "$WORK/mdfind.args" 2>/dev/null; then
    printf '  ok    queries Spotlight by bundle id\n'; PASS=$((PASS + 1))
else
    printf '  FAIL  queries Spotlight by bundle id\n        args: %s\n' \
        "$(cat "$WORK/mdfind.args" 2>/dev/null)"; FAIL=$((FAIL + 1))
fi

# 5. A stale index pointing at a deleted app must not count as installed.
check "ignores a path that no longer exists" "" \
    "$(STUB_MDFIND="$WORK/gone/SwiftBar.app" run_case "$H2")"

# 6. Genuinely absent. Skipped when the test machine really has it in
#    /Applications, which the function checks unconditionally.
if [ -d "/Applications/SwiftBar.app" ]; then
    printf '  skip  reports nothing when absent (/Applications has a real copy)\n'
else
    check "reports nothing when absent" "" "$(run_case "$H2")"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
