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

The extension presents the supplied Omarchy-style reference as an extension-local, 443px dark panel with a thin `#d8754f` border and popup-local `Ubuntu Sans Mono` fallback. It uses GNOME Shell 50.1 `PopupMenu`, `PopupMenuItem`, `PopupSwitchMenuItem`, `PopupSubMenuMenuItem`, `St.Bin`, and `St.BoxLayout` actors; it does not use HTML/CSS or change global fonts/theme settings.

The main panel contains a generic symbolic headphone icon, **AirPods**, and muted **Connected** state. **BATTERY** is rendered as Left/Right/Case horizontal rows: a 220px `St.Bin` track with a fixed-pixel `St.Widget` fill derived from a current numeric observation, percentage, and only observed `In ear` or `Charging` status. Missing, invalid, or stale data renders `Unavailable`; freshness evidence remains in **More settings → Diagnostics**.

**LISTENING MODE** is a vertical list of capability-gated Off, Transparency, Adaptive, and Noise Cancellation items. The observed mode is brighter and gets a right-aligned checkmark; no pills or tiles appear in the main panel. Clicks restore their observed selection until status readback.

Capability plus observed-state gating controls the inline native Conversation Awareness and One-Bud ANC `PopupSwitchMenuItem` rows. Their descriptions explain volume lowering and one-pod ANC. Unknown state is not displayed as a false Off value. Ear detection is an inline submenu with the observed right-aligned choice in Shell 50.1's single native expander. The adaptive level submenu appears only where Adaptive is currently observed and supported.

Music/Meeting, Dictation mic, diagnostics, adaptive level, and connect/disconnect remain available through **More settings**, keeping the reference panel uncluttered. Desired versus observed state, PipeWire profile/codec strings, routing receipts, policy detail, full battery telemetry, stale detail, and Refresh status are confined to **More settings → Diagnostics**.

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
