# Native GNOME popup UI and backend contract

UUID: `gnome-airpods-companion@dosment.github.io`; extension files live directly in `extension/`.

The prior personalized visual concept is not published as product documentation. This document describes the implemented UI; it contains no runtime screenshot claim.

## Popup presentation

The extension uses a standard `PanelMenu.Button` and `PopupMenu` hierarchy. Its public identity is always **AirPods**: a Bluetooth `device_name` remains backend data for targeting and is never rendered.

### Disconnected

The popup shows:

1. **AirPods** and a muted **Disconnected** state.
2. `Connect to see battery levels`.
3. The **Dictation mic** and **More settings** submenus, so their choices remain reachable.
4. A neutral **Connect** action with a network icon.

It does not render battery, audio-mode, or noise-control sections while disconnected. A fresh disconnected state permits Connect; a stale retained status permits no writes.

### Connected

The popup uses a homogeneous GNOME `St.BoxLayout` for three equal Left/Right/Case battery columns (or one headset item), with centered symbolic icon, percentage, and muted label. Missing, invalid, or stale values render as `Unavailable`; zero is shown only when measured and current. Freshness is not inferred from a successful read and is shown only in **Diagnostics**, including stale retained observations and unknown observation age.

**Audio mode** uses a homogeneous native `St.BoxLayout` for equal padded `St.Button` choices; supported **Noise control** uses the same layout for equal capability-gated tiles with an icon above Off, Transparency, Cancellation, and Adaptive. Each `St.Button` is an `St.Bin` with one `St.BoxLayout` child. Buttons carry GNOME Shell's native `button` class, so its `:checked` selected fill and `:focus` treatment remain theme-provided; the extension only adds restrained checked weight and focus boundary. The observed PipeWire profile controls the checked state and a click restores that state until a status readback, preventing optimistic hardware state. A2DP maps to Music; `headset-head-unit`, HFP, and HSP map to Meeting; unknown profiles select neither.

The audio subtitle is one of:

- `High-quality playback`
- `Headset microphone · reduced playback quality`
- `Audio mode unavailable`

A pending request receives the short `Mode change pending` notice. Applying and command failures also use short main-menu notices. Desired versus observed state, PipeWire profile/codec strings, routing receipts, policy detail, full battery telemetry, stale detail, and Refresh status are confined to **More settings → Diagnostics**.

**Dictation mic** uses a generic `AirPods microphone` label for AirPods sources while retaining literal PipeWire source identifiers for validation and argv. Its controls are capability and status gated; no status text claims a capture was verified or changes the Ubuntu default microphone.

`extension/stylesheet.css` is extension-scoped and inherits GNOME fonts and theme colors. It provides restrained hierarchy, compact spacing, muted supporting labels, truncation, and insensitive states without changing the global GNOME theme. Keyboard focus uses supported `border` and `box-shadow` properties rather than CSS `outline`. The Dictation mic value is the sole child of the native submenu expander and therefore expands right-aligned without competing with the arrow, which remains last. This relies on GNOME Shell 50.1's internal `popup-menu-item-expander` child topology; it uses public actor traversal rather than a private field, but must be re-inspected before supporting a Shell version with a changed `PopupSubMenuMenuItem` implementation.

## Normalized Apple contract

`apple` contains `available: boolean`, optional `stale: boolean`, `error: string|null`, `battery`, `capabilities`, and `state`. Battery entries are `{available, level, charging, in_ear, stale, freshness}`. Missing data is never fabricated. Capabilities must be explicit: absent flags grant no Apple controls.

Allowed backend verbs remain exactly `noise:off|anc|transparency|adaptive`, `ca:on|off`, `onebud:on|off`, `ear:one|both|off`, and `adaptive:N` (0–100 only while observed Adaptive mode is active). The frontend passes these only as `apple VERB`; no shell interpolation, arbitrary verbs, protocol packets, or backend command-route changes were introduced. A successful ctl command confirms delivery only; displayed state comes from later readback.

## Verification boundary

- `node --test tests/frontend*.test.mjs` covers schema/parser validation, generic public labels, literal argv preservation, disconnected section gating, no-invented battery values, stale/invalid `Unavailable` batteries with diagnostics-only detail, symbolic centered battery widgets, real homogeneous layout properties, native submenu child ordering with the arrow last, native checked button styling, observed-profile selection, short notices, diagnostics containment, stale/disconnected gates, one-child `St.Bin` content, timeout/cleanup, and mocked controller lifecycle. These controller tests use fakes and are **not** a real Shell load.
- `gjs -m extension/model.js`, `node --check extension/model.js`, and `node --check extension/extension.js` validate the pure module/syntax boundary.
- Shell resource inspection verifies the installed `extension.js`, `main.js`, `panelMenu.js`, and `popupMenu.js` resource paths. This is API inspection, not running-extension verification.

## UI-only extension upgrade and rollback

Install the four extension UI files into a separate, unique state directory:

```bash
python3 scripts/manage-install.py install-extension --state "$HOME/.local/state/gnome-airpods-companion/ui-upgrade-<unique>"
```

Log out and back in before evaluating the change; this process makes no live-reload claim. To roll back the UI-only upgrade, run the corresponding uninstall with the **same** state directory, then log out and back in again:

```bash
python3 scripts/manage-install.py uninstall --state "$HOME/.local/state/gnome-airpods-companion/ui-upgrade-<unique>"
```

Perform this rollback before any original full uninstall, so the UI-only manifest can restore its backups.

No install, enable, GUI automation, audio mutation, hardware-control test, recording test, commit, or push is part of this change. Install through the agreed installer, enable the extension, and have the user verify real Shell layout, keyboard navigation, active profile readback, actual battery/telemetry freshness, supported Apple controls, dictation routing, and disable/re-enable. A first Wayland load may require user-performed logout/login; do not restart Shell through `Alt-F2 r`.
