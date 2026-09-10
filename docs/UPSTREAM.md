# Pinned LibrePods backend audit

## Provenance and scope

Source: <https://github.com/thisisgm/omarchy-pods/tree/fff7fec600a5b9a61cdb40e93eccbcceb4b8f824/daemon>.
Exact commit: `fff7fec600a5b9a61cdb40e93eccbcceb4b8f824`.
The fork's `daemon/UPSTREAM.md` attributes the original Linux subtree to
Kavish Devar's <https://github.com/kavishdevar/librepods>, fork point `29a914c`.
That abbreviated ancestor is an attribution, **not** our fetch pin.

Only the daemon is reused. No Omarchy setup, Quickshell, desktop replacement,
root module, Android app or frontend files are installed. `--headless` avoids
creating the Qt GUI, but the executable still builds/links Qt GUI libraries.
This audit is source-level, not hardware certification or a complete security review.

## Policy patch

`patches/0001-controls-only.patch` changes only
`daemon/media/mediacontroller.cpp`. There is no inspected supported setting
that disables all automatic profile activation: disabling ear detection alone
leaves startup/connect/wake/activation paths intact.

The patch makes these policy entry points inert:

- `activateA2dpProfile`: no profile selection or volume-snap activation.
- `activateA2dpProfileWithRetry`: retain only device identity/card discovery,
  required by ear-detection and Conversation Awareness; start no retry chain.
- `attemptA2dpActivation`: no delayed profile changes.
- `restartWirePlumber`: no restart of the audio session.
- `removeAudioOutputDevice`: never select card profile `off` when buds leave ears.

All startup, wake, reconnect and ear callbacks consequently cannot override a
persistent Meeting profile. Existing upstream log strings at call sites can
still say activation was attempted; those are not evidence of profile changes.
ANC packets, battery, capabilities, IPC and ear-detection MPRIS pause/resume
remain unchanged. Conversation Awareness still ducks/restores volume. Thus
“controls-only” means **no audio profile policy**, not a passive daemon: ear
behavior and CA can affect playback/volume. Do not start it during uncoordinated
recording. The patch does not set any default microphone or default output.

Tests: `patches/test_controls_only.py` checks exact allowed entry-point bodies,
absence of profile writes/volume-snap calls, preserved controls/ear playback,
and AirPods 4 ANC model identities. On unmodified pin it ran RED (six failing
assertions); on patched source both test cases ran GREEN. These are explicit
structural regression guards, **not** compiled Qt integration tests.
`patches/test_build_script.py` ran RED before the builder existed and GREEN
after implementation, exercising real archive extraction, patch application,
source tests and provenance output, with no daemon launch.

## Repeatable safe preparation/build

From the project root:

```sh
python3 scripts/build-librepods.py --prepare-only
python3 patches/test_build_script.py
python3 scripts/build-librepods.py
```

The script refuses root, uses umask 0077, checks the origin URL, and archives
only `daemon/` from the exact Git object, ignoring changes in the cached
worktree. It applies the version-pinned patch with `git apply --check`, then
runs structural tests. Each invocation retains a new private directory under
`~/.cache/gnome-airpods-companion/build-fff7fec600a5-*`; JSON stdout gives its
paths and patch SHA-256. The cache clone is
`~/.cache/gnome-airpods-companion/upstream`. There is no reset/clean of existing
work, no package install, no runtime daemon execution, no service activation,
no Bluetooth connection, and no access to live user settings.

Normal mode runs CMake/Ninja with C++17, Release, BUILD_TESTING=OFF and builds
only `librepods` and `librepods-ctl`. Two build jobs bound resource use. It never
runs `cmake --install`. Review and selectively run upstream Qt unit tests in an
isolated environment after dependencies exist; the builder deliberately does
not start runtime/stress tests against the session.

### Actual result on the audit host

Preparation and patch tests passed. The initial build was blocked by missing
CMake, Ninja, pkg-config and development libraries. After the user installed
the Ubuntu development packages below, the full CMake/Ninja Release build
completed successfully for both `librepods` and `librepods-ctl`. Both are ELF
binaries with all dynamic dependencies resolved on the build host. The Apple
installer completed a temporary-prefix install/uninstall round trip, and
installed binary hashes matched the build artifacts. No daemon was started;
Bluetooth permissions, GNOME service sandboxing and hardware behavior remain
unverified.

Exact requested apt package set (installation is a separate user-authorized step):

```text
build-essential git cmake ninja-build pkg-config
qt6-base-dev qt6-declarative-dev qt6-connectivity-dev
qt6-tools-dev qt6-tools-dev-tools libpulse-dev libssl-dev
```

These map to actual CMake requirements: Quick/QuickControls2/Widgets/Bluetooth/
DBus/LinguistTools, OpenSSL, pkg-config libpulse. No Qt Multimedia dependency
appears in this pinned CMake despite the inherited README listing it.
Use the host's modern Qt: the source calls `GenericStateLocation` and
`QStyleHints::setColorScheme`, so older Ubuntu Qt releases are not presumed
compatible merely because CMake says Qt6. Runtime needs a working user session
bus, BlueZ, and the PulseAudio protocol (normally pipewire-pulse); `bluetoothctl`
from `bluez` is used by connect/disconnect/forget verbs. Do not replace Ubuntu's
audio server. Headless operation requires no Quickshell or playerctl.

### Exact upstream installation rules (not executed)

With CMAKE_INSTALL_BINDIR=bin and prefix `~/.local`, CMake declares:

```text
bin/librepods
bin/librepods-ctl
share/applications/me.kavishdevar.librepods.desktop
share/icons/hicolor/scalable/apps/librepods.svg
share/systemd/user/librepods.service
share/openpods/translations/openpods_tr.qm
```

There is no upstream `install_manifest.txt` because the CMake install target
was deliberately not run. The above is the source-declared upstream manifest,
not a claim that those files were installed. `scripts/install-librepods.py`
uses a narrower project-owned layout: two binaries under
`share/gnome-airpods-companion/libexec`, provenance/notices under `upstream`,
and `share/systemd/user/gnome-airpods-controls.service`. Its separate restoration
manifest is stored outside the repository. It does not install the upstream
launcher/tray or start the service. The builder installs **zero files** outside
its cache.

## Permissions, privileges, and secrets

- No sudo, setcap, root check or privileged installer is needed by the inspected
  daemon build. QtBluetooth uses BlueZ and L2CAP; this is designed as a user
  service. The pinned service explicitly has `NoNewPrivileges=yes` and does not
  request capabilities. `CapabilityBoundingSet=`, `ProtectKernelModules=`,
  `ProtectKernelLogs=`, and `ProtectClock=` are intentionally omitted because
  this user manager fails each before `exec` with `218/CAPABILITIES`; the
  daemon still runs unprivileged. Actual
  controller/BlueZ/kernel permissions remain a hardware gate; do not “fix”
  permission errors by running as root or adding broad capabilities.
- Socket: `$XDG_RUNTIME_DIR/librepods.sock`; missing runtime directory is fatal,
  no `/tmp` fallback. Server requests `UserAccessOption`. Runtime directory
  ownership/mode is trusted rather than validated; use the systemd user
  environment, not an attacker-controlled XDG_RUNTIME_DIR. Same-user clients
  can issue destructive `forget`; the companion must not expose that verb.
- Status: atomic QSaveFile, mode 0600 before commit. State directory is 0700 in
  the service. JSON contains names/model identity but no pairing keys or MAC
  field. Logs **do** contain device names/MACs. Never publish real state/logs.
- Settings: `~/.config/AirPodsTrayApp/AirPodsTrayApp.conf` (or XDG_CONFIG_HOME),
  including `DeviceInfo/magicAccIRK` and `DeviceInfo/magicAccEncKey` in QSettings,
  not a secret-service/keyring. These are private pairing/decryption material.
  `restrictSettingsAccess()` syncs then sets directory 0700/file 0600, and does
  not check chmod errors. Therefore enforce service UMask=0077 **before first
  write**; do not rely on post-write chmod for protection.
- **Residual secret-logging risk:** `main.cpp:1261` logs every received raw
  packet at debug level *before* recognizing a Magic Cloud Keys response.
  The later key-specific log prints lengths only, but that does not redact the
  earlier raw packet. The service's `QT_LOGGING_RULES=openpods.debug=false`
  must be retained; never use `--debug`/raw Bluetooth captures in support logs.
  This risk is documented, not patched by the profile-policy change.
- Cross-device relay defaults off via `crossdevice/enabled=false`; it can relay
  raw packets to a configured phone when enabled. Preserve off for this product.
  Existing upstream settings can enable it: inspect/migrate only with consent,
  never silently adopt arbitrary old configuration.
- The inherited service has strict filesystem and syscall sandboxing,
  owner-only state/config directories, and no capabilities. Whether all user
  namespace/sandbox directives work on this Ubuntu session is unverified.
  Do not enable it yet or silently weaken it on failure.

## GPL and distribution

The root Omarchy widget's MIT license does **not** cover this daemon. Retain
`daemon/LICENSE` (GPL v3), `daemon/UPSTREAM.md`, original copyright notices and
third-party notices (including QR-Code-generator) with source. Our patch to
the GPL daemon is distributed under GPL-3.0; retain its modification notice
and exact revision/patch hash. The original source archive includes ancillary
assets (including an uncompiled SF Symbols font); no license clearance for
redistributing that font is claimed here. Do not add it to a binary package.

When distributing modified binaries, provide their complete corresponding
source by a GPL-compliant method—not merely a moving upstream URL. Publish a
release source archive containing the exact daemon tree, applied patch, build
instructions/scripts and all required notices alongside binaries; retain the
unmodified pin and patch provenance. Resolve licensing of ancillary assets
before release. Dependency library licensing obligations also still apply.
Keep protocol implementation separate from the companion IPC client, but do
not claim separation itself is legal advice or a blanket licensing exemption.

See [UPSTREAM-CONTRACT.md](UPSTREAM-CONTRACT.md) for the source-derived IPC
schema and important limits on “actual” readback.
