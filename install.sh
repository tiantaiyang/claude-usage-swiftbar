#!/bin/sh
# One-command installer for the Claude usage SwiftBar plugin.
#
#   /bin/sh -c "$(curl -fsSL https://raw.githubusercontent.com/tiantaiyang/claude-usage-swiftbar/main/install.sh)"
#
# Works either piped from curl or run from a checkout. Re-running is safe: it
# reuses SwiftBar's existing plugin directory rather than repointing it, so
# other plugins are left alone.
#
# Non-interactive use (skips all prompts):
#   NONINTERACTIVE=1 SWIFTBAR_APPDIR=~/Applications INSTALL_DIR=~/src/x ./install.sh

set -eu

REPO_URL="https://github.com/tiantaiyang/claude-usage-swiftbar.git"
PLUGIN_NAME="claude-usage.2m.py"
BUNDLE_ID="com.ameba.SwiftBar"
KEYCHAIN_SERVICE="Claude Code-credentials"
DEFAULT_APPDIR="$HOME/Applications"
DEFAULT_INSTALL_DIR="$HOME/Developer/claude-usage-swiftbar"
DEFAULT_PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
note() { printf '    %s\n' "$1"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '\n\033[31merror:\033[0m %s\n\n' "$1" >&2; exit 1; }

# Prompt on /dev/tty so this works even when the script itself arrives on stdin
# (`curl | sh`). Falls back to the default when there is no terminal.
ask() {
    _prompt="$1"
    _default="$2"
    if [ -n "${NONINTERACTIVE:-}" ] || [ ! -r /dev/tty ]; then
        printf '%s\n' "$_default"
        return
    fi
    printf '    %s [%s]: ' "$_prompt" "$_default" > /dev/tty
    IFS= read -r _answer < /dev/tty || _answer=""
    [ -n "$_answer" ] || _answer="$_default"
    case "$_answer" in
        "~") _answer="$HOME" ;;
        "~/"*) _answer="$HOME/${_answer#\~/}" ;;
    esac
    printf '%s\n' "$_answer"
}

find_brew() {
    for _candidate in brew /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if command -v "$_candidate" >/dev/null 2>&1; then
            command -v "$_candidate"
            return 0
        fi
    done
    return 1
}

find_swiftbar() {
    for _dir in "/Applications" "$HOME/Applications" "${SWIFTBAR_APPDIR:-}"; do
        [ -n "$_dir" ] || continue
        [ -d "$_dir/SwiftBar.app" ] && printf '%s\n' "$_dir/SwiftBar.app" && return 0
    done
    _found=$(mdfind -name "SwiftBar.app" 2>/dev/null | grep '/SwiftBar\.app$' | head -1) || _found=""
    [ -n "$_found" ] && [ -d "$_found" ] && printf '%s\n' "$_found" && return 0
    return 1
}

# ---------------------------------------------------------------- 1. platform

step "Checking this Mac"
[ "$(uname -s)" = "Darwin" ] || fail "this installer is macOS only (SwiftBar is a macOS app)"
note "macOS $(sw_vers -productVersion)"

# /usr/bin/python3 comes from the Xcode Command Line Tools, not the base system.
# Without them that path opens an installer dialog instead of running, and the
# plugin would show up in SwiftBar as broken. Fail here with the fix instead.
if /usr/bin/python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' 2>/dev/null; then
    note "$(/usr/bin/python3 -V 2>&1) at /usr/bin/python3"
else
    fail "/usr/bin/python3 is unusable (the Xcode Command Line Tools provide it).
       Run this, then re-run the installer:

           xcode-select --install"
fi

# ---------------------------------------------------------------- 2. swiftbar

step "Checking SwiftBar"
SWIFTBAR_APP=$(find_swiftbar || true)
if [ -n "$SWIFTBAR_APP" ]; then
    note "already installed: $SWIFTBAR_APP"
else
    note "SwiftBar is not installed yet."
    BREW=$(find_brew || true)
    [ -n "$BREW" ] || fail "Homebrew is needed to install SwiftBar but was not found.
       Install Homebrew first: https://brew.sh"
    note "using Homebrew at $BREW"
    note ""
    note "Installing into your home Applications folder avoids the admin"
    note "password prompt that writing to /Applications triggers."
    APPDIR=$(ask "Install SwiftBar.app into which folder?" "${SWIFTBAR_APPDIR:-$DEFAULT_APPDIR}")
    mkdir -p "$APPDIR" || fail "cannot create $APPDIR"
    [ -w "$APPDIR" ] || fail "$APPDIR is not writable"
    note "running: brew install --cask swiftbar --appdir=$APPDIR"
    "$BREW" install --cask swiftbar --appdir="$APPDIR" \
        || fail "brew failed to install SwiftBar"
    SWIFTBAR_APP=$(SWIFTBAR_APPDIR="$APPDIR" find_swiftbar || true)
    [ -n "$SWIFTBAR_APP" ] || fail "SwiftBar installed but could not be found under $APPDIR"
    note "installed: $SWIFTBAR_APP"
fi

# -------------------------------------------------------------------- 3. code

step "Getting the plugin"
SRC=""
case "${0:-}" in
    */*)
        _here=$(cd "$(dirname "$0")" 2>/dev/null && pwd) || _here=""
        [ -n "$_here" ] && [ -f "$_here/plugins/$PLUGIN_NAME" ] && SRC="$_here"
        ;;
esac

if [ -n "$SRC" ]; then
    note "using this checkout: $SRC"
else
    command -v git >/dev/null 2>&1 || fail "git is required to download the plugin"
    SRC=$(ask "Where should the plugin repo live?" "${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}")
    if [ -d "$SRC/.git" ]; then
        note "updating existing checkout at $SRC"
        git -C "$SRC" pull --ff-only >/dev/null 2>&1 \
            || warn "could not fast-forward $SRC; using it as-is"
    else
        [ -e "$SRC" ] && [ ! -d "$SRC" ] && fail "$SRC exists and is not a directory"
        if [ -d "$SRC" ] && [ -n "$(ls -A "$SRC" 2>/dev/null)" ]; then
            fail "$SRC already exists and is not empty"
        fi
        mkdir -p "$(dirname "$SRC")"
        note "cloning into $SRC"
        git clone --depth 1 "$REPO_URL" "$SRC" >/dev/null 2>&1 \
            || fail "could not clone $REPO_URL"
    fi
fi
PLUGIN_SRC="$SRC/plugins/$PLUGIN_NAME"
[ -f "$PLUGIN_SRC" ] || fail "$PLUGIN_SRC is missing"

# ------------------------------------------------------------- 4. credentials

step "Checking Claude Code sign-in"
if security find-generic-password -s "$KEYCHAIN_SERVICE" >/dev/null 2>&1; then
    note "keychain item \"$KEYCHAIN_SERVICE\" is present"
else
    warn "no \"$KEYCHAIN_SERVICE\" keychain item found."
    note "The plugin will read \"Not signed in to Claude Code\" until you run"
    note "  claude    and then  /login"
    note "Continuing anyway; nothing else needs to change afterwards."
fi

# --------------------------------------------------------------- 5. plugin dir

step "Wiring up SwiftBar"
PLUGIN_DIR=$(defaults read "$BUNDLE_ID" PluginDirectory 2>/dev/null || true)
PREF_CHANGED=""
if [ -n "$PLUGIN_DIR" ]; then
    note "reusing SwiftBar's configured plugin folder: $PLUGIN_DIR"
else
    PLUGIN_DIR="$DEFAULT_PLUGIN_DIR"
    mkdir -p "$PLUGIN_DIR"
    defaults write "$BUNDLE_ID" PluginDirectory -string "$PLUGIN_DIR"
    PREF_CHANGED="yes"
    note "set plugin folder to $PLUGIN_DIR"
    note "(setting this up front skips SwiftBar's first-run folder dialog)"
fi
mkdir -p "$PLUGIN_DIR"

chmod +x "$PLUGIN_SRC"
ln -sfn "$PLUGIN_SRC" "$PLUGIN_DIR/$PLUGIN_NAME"
note "linked $PLUGIN_NAME -> $PLUGIN_SRC"

# ------------------------------------------------------------------ 6. verify

step "Testing the plugin"
FIRST_LINE=$("$PLUGIN_SRC" 2>&1 | head -1) || true
[ -n "$FIRST_LINE" ] || fail "the plugin produced no output"
note "menu bar will show:  $FIRST_LINE"

# ------------------------------------------------------------------- 7. launch

step "Starting SwiftBar"
if pgrep -x SwiftBar >/dev/null 2>&1; then
    if [ -n "$PREF_CHANGED" ]; then
        note "restarting SwiftBar to pick up the new plugin folder"
        osascript -e 'quit app "SwiftBar"' >/dev/null 2>&1 || true
        sleep 2
        open -a "$SWIFTBAR_APP"
    else
        open -g "swiftbar://refreshallplugins" >/dev/null 2>&1 || true
        note "already running; asked it to refresh"
    fi
else
    open -a "$SWIFTBAR_APP"
    note "launched SwiftBar"
fi

cat <<'DONE'

    Done. Look for the ◱ item in your menu bar.

    Two things to know:
      * If macOS asks for keychain access, choose "Always Allow" — otherwise
        the plugin can't read your token and will report "Not signed in".
      * To launch SwiftBar automatically, enable "Start at Login" in its
        own preferences.

DONE
