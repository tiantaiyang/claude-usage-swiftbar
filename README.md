# claude-usage-swiftbar

A SwiftBar menu-bar plugin showing Claude quota: the 5-hour session window,
weekly limits, and extra-usage credits.

```
􀍽 69% · 2h08 · ⚠️      ← 􀍽 is the gauge.medium SF Symbol
---
Claude usage — Max 5x (team)
Session (5h)    69%  ▓▓▓▓▓▓░░░░  resets 14:10 (in 2h 41m)
Weekly (all)    25%  ▓▓░░░░░░░░  resets Sun 08-02 02:00 (in 5d 14h)
Weekly (Fable)   0%  ░░░░░░░░░░
Extra usage    100%  ▓▓▓▓▓▓▓▓▓▓  $50.25 / $50.00 ⚠️
```

The menu bar carries a native SF Symbol, the session percentage, a countdown to
the 5-hour window reset, and a ⚠️ once the session or a weekly quota reaches
90%. The icon is a template image, so it follows the menu bar's light and dark
appearance and stays crisp on any display; swap it for any SF Symbol name with
`CLAUDE_USAGE_SFIMAGE`. Extra-usage
credits are reported in the dropdown only — they can sit over their cap
indefinitely, so they would otherwise light the warning permanently. The
numbers are the same ones `/usage` reports inside Claude Code — they come from
the account's own usage endpoint, not from estimating token counts.

## How it works

`GET https://api.anthropic.com/api/oauth/usage` with the OAuth access token
that Claude Code stores in the login keychain (service
`Claude Code-credentials`).

Two rules the code holds to:

1. **It never refreshes the OAuth token.** Refreshing from a second process
   rotates the refresh token and can sign you out of Claude Code. On a 401 the
   plugin says so and waits for Claude Code to refresh on its own.
2. **The token never reaches disk.** It is read into memory per run and passed
   only in the `Authorization` header — never in a URL or argv. `cache.save()`
   refuses to write any record containing a credential-shaped key, and
   `Credentials.__repr__` is redacted so it cannot leak into an error message.

The endpoint is undocumented and may change. Unknown limit kinds are rendered
with a humanised label rather than dropped, and any failure degrades to the
last good snapshot (marked `⌛`) instead of breaking the menu bar.

## Install

One command, on any Mac:

```sh
/bin/sh -c "$(curl -fsSL https://raw.githubusercontent.com/tiantaiyang/claude-usage-swiftbar/main/install.sh)"
```

It will:

1. verify `/usr/bin/python3` works, failing fast with the fix if not;
2. install SwiftBar via Homebrew if it is missing — asking which folder to put
   `SwiftBar.app` in, and passing `--appdir` so writing to `/Applications`
   never prompts for an admin password;
3. clone this repo to `~/Developer/claude-usage-swiftbar` (override with
   `INSTALL_DIR`; it is not worth a prompt);
4. check that Claude Code is signed in;
5. reuse SwiftBar's existing plugin folder if one is configured (other plugins
   are left alone), otherwise set one — which also skips SwiftBar's first-run
   folder dialog;
6. link the plugin, smoke test it, and start SwiftBar.

Re-running it is safe. **When SwiftBar is already installed there is nothing to
ask, so it runs straight through with no prompts.** The only question is which
folder to put `SwiftBar.app` in, and only when it actually has to install it —
answering it feeds `brew install --cask swiftbar --appdir=...`, which is what
keeps `/Applications` from demanding an admin password.

The prompt reads from `/dev/tty`, so it works under `curl | sh` too. To answer
everything up front:

```sh
SWIFTBAR_APPDIR=~/Applications INSTALL_DIR=~/Developer/claude-usage-swiftbar \
  /bin/sh -c "$(curl -fsSL https://raw.githubusercontent.com/tiantaiyang/claude-usage-swiftbar/main/install.sh)"
```

SwiftBar is located by checking the usual folders, then a running instance,
then LaunchServices, then Spotlight by bundle id — so a copy installed
somewhere unusual is still found rather than installed a second time.

From an existing checkout, `./install.sh` does the same thing without cloning.

Pick a stable folder for the repo. SwiftBar is pointed at a symlink into it, so
a location you periodically clear out — `/tmp`, `~/Downloads` — will leave a
dangling link and the menu-bar item will silently disappear.

If the API rate-limits you (HTTP 429), the plugin stops polling until the
`Retry-After` window passes and shows `Rate limited until HH:MM` over the last
known numbers, so several machines polling the same account back off on their
own rather than making it worse.

### What each Mac needs

| Requirement | Handled by the installer? |
|---|---|
| A working `/usr/bin/python3` | checked; you run `xcode-select --install` if missing |
| SwiftBar | installed for you via Homebrew if absent |
| Homebrew | only needed when SwiftBar is missing; not installed for you |
| Claude Code signed in | checked; warns and continues (`claude` then `/login`) |

`/usr/bin/python3` on macOS is provided by the Xcode Command Line Tools, not the
base system. On a Mac without them that path opens an installer dialog instead
of running, and the plugin would look broken — so the installer stops there
rather than leaving you to debug it in the menu bar.

The first time SwiftBar runs the plugin, macOS may ask for keychain access (the
request comes from `/usr/bin/security`). Choose **Always Allow**, or the plugin
will show "Not signed in to Claude Code".

### Manual install

```sh
PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
mkdir -p "$PLUGIN_DIR"
defaults write com.ameba.SwiftBar PluginDirectory -string "$PLUGIN_DIR"
ln -sf "$PWD/plugins/claude-usage.30s.py" "$PLUGIN_DIR/claude-usage.30s.py"
chmod +x plugins/claude-usage.30s.py
open -a SwiftBar
```

The symlink means edits in this repo take effect on the next refresh. If a
SwiftBar version ever ignores symlinked plugins, copy the file instead.

The interval in the filename is how often the plugin **redraws**, not how often
it calls the API. It runs every 30 seconds so the countdown moves, but only
fetches when the cached snapshot is older than `CLAUDE_USAGE_FETCH_TTL`
(120s) — so redrawing four times as often costs no extra requests. Raise the
TTL to fetch less; rename the file to redraw less.

To start SwiftBar at login, enable it in SwiftBar's own preferences.

## Configuration

Every tunable is an environment variable; defaults live in
`claude_usage/config.py`.

| Variable | Default |
|---|---|
| `CLAUDE_USAGE_API_URL` | `https://api.anthropic.com/api/oauth/usage` |
| `CLAUDE_USAGE_BETA_HEADER` | `oauth-2025-04-20` |
| `CLAUDE_USAGE_KEYCHAIN_SERVICE` | `Claude Code-credentials` |
| `CLAUDE_USAGE_TIMEOUT` | `8` seconds |
| `CLAUDE_USAGE_WARN_PCT` / `_CRIT_PCT` | `90` / `95` — the menu-bar ⚠️ appears once any quota limit reaches `WARN_PCT` |
| `CLAUDE_USAGE_BAR_WIDTH` | `10` |
| `CLAUDE_USAGE_SFIMAGE` | `gauge.medium` — SF Symbol for the menu-bar icon; set to `""` to use the text glyph instead |
| `CLAUDE_USAGE_GLYPH` | `◱` — fallback used only when `SFIMAGE` is empty |
| `CLAUDE_USAGE_STALE_AFTER` | `900` seconds |
| `CLAUDE_USAGE_BACKOFF` | `300` seconds (used when a 429 omits `Retry-After`) |
| `CLAUDE_USAGE_FETCH_TTL` | `120` seconds — how old the cache must be before a real request |
| `CLAUDE_USAGE_CACHE_PATH` | `~/Library/Caches/claude-usage-swiftbar/snapshot.json` |
| `CLAUDE_USAGE_PAGE_URL` | `https://claude.ai/settings/usage` |

## Layout

| Path | Purpose |
|---|---|
| `claude_usage/config.py` | tunables, env overrides |
| `claude_usage/keychain.py` | read credentials via `/usr/bin/security` |
| `claude_usage/api.py` | usage endpoint client, typed errors |
| `claude_usage/model.py` | payload → immutable rows (pure) |
| `claude_usage/render.py` | rows → SwiftBar output (pure) |
| `claude_usage/cache.py` | atomic, owner-only snapshot |
| `claude_usage/cli.py` | orchestration and degraded-state mapping |
| `plugins/claude-usage.30s.py` | SwiftBar entry point |

Production code is standard library only: SwiftBar runs the plugin under
`/usr/bin/python3` with no access to nvm, Homebrew Python, or a virtualenv.

## Tests

Zero dependencies, so this works on a fresh Mac:

```sh
/usr/bin/python3 -m unittest discover -s tests
```

The tests are plain `unittest.TestCase` classes, which pytest also collects
natively — so with a virtualenv you get the usual coverage report:

```sh
/usr/bin/python3 -m venv .venv && .venv/bin/pip install -q pytest pytest-cov ruff
.venv/bin/pytest tests --cov=claude_usage --cov-report=term-missing
.venv/bin/ruff check claude_usage plugins tests
```

`unittest` is what the plugin's own runtime supports; pytest is a convenience
for local work. The `.venv` is a test-only artifact and is gitignored — the
plugin itself never sees it.

## Checking degraded states by hand

```sh
# Not signed in
CLAUDE_USAGE_KEYCHAIN_SERVICE=nope /usr/bin/python3 plugins/claude-usage.30s.py

# Offline: falls back to the cached snapshot, marked ⌛
CLAUDE_USAGE_API_URL=http://127.0.0.1:1/ /usr/bin/python3 plugins/claude-usage.30s.py
```
