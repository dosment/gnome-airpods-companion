# GNOME AirPods Companion

A GNOME-native AirPods menu with explicit Music/Meeting audio modes, Apple listening controls, and optional Voxtype microphone selection.

**Under development. Not yet a tested release.** Hardware and desktop acceptance are pending. See [the product scope](docs/PRODUCT.md).

## Design

- Keep GNOME, BlueZ, PipeWire, and WirePlumber; do not replace the desktop or Bluetooth stack.
- Separate saved audio intent from the observed profile. Native WirePlumber policy controls microphone-driven switching and reconnection by default; only explicit mode commands or opted-in legacy enforcement route playback to the AirPods sink.
- Companion profile changes are manual by default: select `mode music` or `mode meeting` when wanted; native WirePlumber autoswitch remains independent. A watcher does not reassert saved intent unless explicitly started with `watch --enforce-profiles`.
- Do not explicitly change Ubuntu's default microphone when switching Music/Meeting modes. Removing a microphone endpoint can still cause PipeWire to pick a fallback.
- Voxtype may follow the system default or use an independently pinned input.
- Reuse version-pinned LibrePods protocol work for battery and supported listening/ear-detection controls; never invent missing telemetry. The native popup presents unavailable or stale values plainly, keeps freshness detail in Diagnostics, and uses GNOME-native checked controls and submenu ordering.
- Install per-user and preserve previous files. No automatic pairing resets, system-service restarts, or device-ID spoofing.

## Development checks

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test
```

Unit tests use explicit fixtures and are not proof of real AirPods behavior. Real desktop, reconnect, call, dictation, listening-control, and rollback tests are separate acceptance gates.

## Installation safety

The file installer is deliberately separate from activation:

```sh
python3 scripts/manage-install.py install
```

It copies the backend, GNOME extension, and user-service unit into `~/.local`. It does **not** enable services, change audio modes, or edit Voxtype settings.

### Recommended audio workflow

Prefer WirePlumber's native microphone-driven profile switching, with the companion watcher stopped/disabled. Relinquish companion policy ownership, restore native autoswitch, and disable any previously enabled watcher:

```sh
systemctl --user disable --now gnome-airpods-companion.service
gnome-airpods-companion policy disable
wpctl settings --save bluetooth.autoswitch-to-headset-profile true
```

This lets AirPods microphone capture activate HFP and lets WirePlumber restore the previous profile (normally A2DP) when capture ends. Reconnect the AirPods if their microphone is not exposed after enabling autoswitch. Select that microphone in the meeting app; muting may leave capture open. The supplied service starts plain `watch`, which does not change profiles or default output. `policy enable` only disables WirePlumber autoswitch; it does not enable background enforcement. For a strictly manual alternative, leave the watcher disabled, run `gnome-airpods-companion policy enable` to disable native autoswitch, and use explicit `mode music` / `mode meeting`. Legacy background profile and output enforcement requires the explicit `gnome-airpods-companion watch --enforce-profiles` opt-in and policy ownership. Profile switching and default-output fallback are separate: when a profile removes a source, PipeWire may independently select another microphone. Without legacy enforcement, the companion routes playback only on explicit mode selection, not automatically on reconnect.

Build and install the separately pinned Apple protocol daemon:

```sh
python3 scripts/build-librepods.py
# Use the exact "work" directory printed by the successful builder:
python3 scripts/install-librepods.py install --work /absolute/path/from/build/output
```

This installs only project-owned private backend binaries, provenance/notices and a separate `gnome-airpods-controls.service`, not the upstream tray application. It does not activate that service. Requirements and audit: [UPSTREAM.md](docs/UPSTREAM.md). Nonstandard `--prefix` is for packaging tests; the supplied services and frontend target the normal per-user `~/.local` location.

The controls daemon installation has its own restoration manifest. After stopping/disabling its service, remove it separately:

```sh
python3 scripts/install-librepods.py uninstall
```

Private pairing configuration is retained; do not publish it or remove it without understanding the pairing implications.

Restoration metadata and prior files are stored under `$XDG_STATE_HOME/gnome-airpods-companion/install` (normally `~/.local/state/gnome-airpods-companion/install`). Reinstallation refuses an existing manifest: uninstall the prior installation first. Uninstallation refuses modified/missing managed files rather than silently destroying local edits.

Before file removal, disable the extension and stop/disable the companion services, and restore any acquired audio policy using the backend's documented restoration command. Then:

```sh
python3 scripts/manage-install.py uninstall
```

Personal configuration is retained. A first GNOME extension installation may require logout/login; do not restart GNOME Shell under Wayland to force discovery.

## Privacy and licensing

No cloud service is required for the companion itself. Do not attach unredacted status files, Bluetooth addresses, microphone/device names, pairing keys, or recorded audio to public issues. Voxtype's own transcription configuration is independent.

GPL-3.0; see [LICENSE](LICENSE). LibrePods-derived components retain their own copyright and provenance notices. This project is not affiliated with Apple, GNOME, Ubuntu, LibrePods, or Omarchy. AirPods is an Apple trademark; Apple product artwork is not included.
