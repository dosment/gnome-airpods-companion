# Backend integration and safety

Python 3 stdlib only. Run `python3 -m unittest discover -s tests -p 'test_backend*.py' -v`.
The executable resolves its real path, so a symlink from `~/.local/bin` to the installed sibling `bin/` + `companion/` tree works.

## Commands

- `status`: read-only JSON schema 1; discovers `pw-dump` and BlueZ `GetManagedObjects` via `busctl`. No pactl dependency, no configuration writes, no service restarts. Missing optional Apple telemetry does not break audio discovery. Missing required probes produce a JSON error and exit 1.
- `select-device ADDRESS`: explicitly selects one known paired AirPods when multiple exist. No pairing/forgetting. Address is private local intent only. Initial automatic selection requires exactly one paired device with AirPods in its BlueZ Name.
- `connect` / `disconnect`: BlueZ Device1 method, followed by readback. Asynchronous completion can return an unconfirmed error; retry **status**, not the mutation.
- `mode music|meeting`: saves desired intent even while disconnected, selects only dynamically enumerated card profile indexes when available, then reads back. Music prefers SBC-XQ; Meeting prefers LC3, then mSBC, then other HFP. Profile not observed is an error, not fabricated success. Neither command nor watcher sets the global default source. When HFP disappears PipeWire itself may pick a fallback microphone.
- `policy enable`: explicit ownership of WirePlumber `bluetooth.autoswitch-to-headset-profile`; journals both runtime and optional saved value before `wpctl settings --save ... false`, then verifies. No status/watch call acquires ownership.
- `policy disable`: restores saved override presence/value and original runtime value, verifies both, then releases ownership. Refuses to overwrite external edits. Resolve conflicts manually with the private intent backup; do not delete it before restoration.
- `watch`: default 2-second polling, only enforces with explicit policy ownership and an explicit desired mode. Three attempted profile writes per connection generation/explicit mode revision, **including failures**; success never resets the budget. Fresh PipeWire IDs/serials are discovered every pass. An external autoswitch change pauses enforcement rather than fighting it. `--iterations N --interval SECONDS` provides finite test/diagnostic runs. Do not run multiple watcher instances. Enable the supplied service only after explicit policy enable; stop it before policy disable/uninstall.

Intent is atomically replaced, mode 0600, under `$XDG_STATE_HOME/gnome-airpods-companion/intent.json` (default `~/.local/state`). Desired mode defaults to null, not Music. State contains personal identifiers and must never be copied into the repository or issue logs. CLI mutations acquire a nonblocking per-user flock; the watcher takes the same mutation lock per enforcement pass, plus its own lifetime singleton lock. The Voxtype launcher has a separate lifetime lock. Read-only status takes no lock and creates no files. Library callers must explicitly use `Backend.exclusive()` around mutations.

## Optional Voxtype: FOLLOW DEFAULT unless pinned

Inspected Voxtype **v1.0.1** `src/audio/cpal_capture.rs`: it uses CPAL's default Linux host, enumerating ALSA devices; a PipeWire node name is not automatically an ALSA device. Installed service inspection showed `/usr/bin/voxtype -q daemon`; read-only extended status identified ALSA device `pipewire`.

- `voxtype default` / `voxtype pin NODE_NAME` save only dictation intent, **never restart a daemon or interrupt an active recording**. Pin must be one current real Audio/Source, with a safely representable node name. These commands do not change any Voxtype configuration settings.
- `voxtype-run` is an optional **service launch wrapper**, not a recording command. It runs `voxtype -q --audio-device pipewire daemon`; in pinned mode its child alone gets `ALSA_CONFIG_PATH` pointing to a private temporary ALSA configuration including `/usr/share/alsa/alsa.conf` and overriding `pcm.!pipewire` with `capture_node "NODE_NAME"`. Playback is not pinned. Default mode has no target override. Existing `ALSA_CONFIG_PATH`/`PIPEWIRE_ALSA` overrides cause refusal rather than silent replacement. An inherited `PIPEWIRE_NODE` is removed so default really follows default.
- Inspected PipeWire's `pipewire-alsa/alsa-plugins/pcm_pipewire.c`: `capture_node` sets `target.object` only for capture. `PIPEWIRE_NODE` sets it indiscriminately, including playback; therefore it is **not** our pinning mechanism.
- To opt in, after backing up and reviewing existing service overrides, explicitly add a dedicated user-service drop-in:

  ```ini
  [Service]
  ExecStart=
  ExecStart=%h/.local/bin/gnome-airpods-companion voxtype-run
  ```

  Do not replace a customized ExecStart blindly. Reload systemd, and restart Voxtype **only after a user-confirmed idle boundary**. Never automate that restart based on a race-prone idle probe. The launcher snapshots intent at launch; routing changes remain pending until that next coordinated restart. The wrapper stores a separate atomic `voxtype-launch.json` receipt only after child creation and clears the matching saved pending flag under the mutation lock. Status exposes desired `mode/source`, separate `effective` launch routing, `integration` (`wrapper_running`, `unknown`, or `stale_receipt`), and `capture_verified:false`. Both supervisor and child identities include Linux boot ID and process start ticks; exited/zombie or reused-PID receipts never establish effective routing. Normal exit removes the receipt. Status recomputes pending from the live launch versus desired intent, so changing intent cannot rewrite the effective snapshot. No receipt means unknown integration, not proof that no Voxtype daemon exists. This proves launch configuration only, not service-drop-in persistence or capture routing. Remove only this owned drop-in to revert, then coordinate another idle restart. No general Voxtype TOML edits are needed.

This wrapper and config generation are boundary-tested without opening a microphone. Actual capture routing, disappearing pinned-source fallback behavior, and service lifecycle still need coordinated hardware acceptance. Pinning is routing preference, not a privacy guarantee against server fallback when a target disappears.

## Apple bridge

Inspected `thisisgm/omarchy-pods` pinned revision `fff7fec600a5b9a61cdb40e93eccbcceb4b8f824`, `daemon/librepods-ctl.cpp`, and `knowledge/librepods-status-schema.md`; upstream agent owns the controls-only daemon patch/build. Never run an unpatched daemon alongside persistent Meeting policy.

Read `$XDG_STATE_HOME/librepods/status.json`, schema_version 1, bounded to 64 KiB. Missing/malformed/unknown schema is unavailable. Battery values are never synthesized; `battery.left/right/case` each has explicit availability and nullable level. Disconnected battery packets remain useful. Missing capability keys remain unknown rather than inferred from a marketing name.

Normalized frontend contract: `apple.capabilities.noise_modes`, `conversation_awareness`, `one_bud_anc`, `ear_detection`, `adaptive_level`; `apple.state.noise_mode` is a string, with matching other state fields. Raw named support flags are also retained. `apple.controls` lists supported fixed CLI verbs. Adaptive slider verbs are validated separately as canonical `adaptive:0` through `adaptive:100` and only while observed Adaptive mode is active.

**Upstream writes only on change.** `age_seconds` is snapshot-file age, not daemon or battery age. For snapshots older than 300 seconds, status queries only the installed absolute `libexec/librepods-ctl status` through the bounded command runner (12-second timeout). Valid replies set `liveness:responsive` and retain supported controls; missing ctl, failure or invalid replies retain the cached battery but mark stale and disable controls. Recent snapshots report `liveness:recent_snapshot`, not independently verified daemon life. Every battery observation has `freshness:unknown`: neither file modification nor a live status reply supplies a measurement timestamp.

`apple VERB` delegates only explicitly supported verbs to the absolute installed-tree `libexec/librepods-ctl` path, never a PATH-selected executable. The optional upstream installer must put the audited pinned binary there; it is not currently installed by this backend. Allowed families: noise, ear, ca, onebud, adaptive. No `forget`, daemon connection commands, arbitrary arguments, or shell. Read back `librepods-ctl status`; `reported_matches` compares the requested field. `confirmation_scope` distinguishes `hardware_observation` for noise mode, `local_policy` for ear behavior, and `daemon_preference` for CA, adaptive level and one-bud ANC. The latter return `confirmed:null` even when matching, because pinned `daemon/main.cpp` setters update local preferences after sending (CA/adaptive even ignore write failure); they do not await device acknowledgement. Ear behavior is the authoritative local media-controller setting, not a hardware acknowledgement. Noise-mode readback is an observation, not proof that this particular command caused it. Normalized `state_sources` preserves the same distinction during polling. The bridge exposes no strong selected-device identity token, so multi-device Apple targeting requires upstream work before claiming correctness for more than one paired set.

## Acceptance state

Read-only live CLI discovery succeeded with a known paired but disconnected device, desired mode null, no active profile, three microphones, default Voxtype intent, and optional Apple bridge unavailable. BlueZ adapter was powered off/blocked at probe time. Autoswitch was true before work and has not been changed. No installs, live config writes, profile switches, audio recording, daemon restarts, commits or pushes were performed.

Known review follow-ups not implemented in this bounded fix: watcher ownership/paused/exhausted state is not yet exported across processes by `status`; installer rollback failure and partially completed uninstall recovery need additional fault-injection tests and recovery journaling. Existing copy-failure rollback coverage does not prove those cases.

Remaining: real mode readback/reconnect, controls-only bridge ANC/battery readback, coordinated Voxtype routing capture, meeting capture, GNOME/service load, conflict recovery and uninstall restoration on actual hardware. Mock-boundary tests do not close those gates.
