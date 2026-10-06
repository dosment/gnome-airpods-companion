# GNOME AirPods Companion

## Agreed scope

Public repository: https://github.com/dosment/gnome-airpods-companion

- GNOME-native full companion; initial hardware acceptance target AirPods 4 with ANC, Ubuntu GNOME 50.
- Saved Music/Meeting intent persists across reconnects/logins but does not enforce the observed profile by default. Default workflow uses WirePlumber's native microphone-driven HFP/A2DP switching with the companion watcher disabled; companion policy disable plus `wpctl settings --save bluetooth.autoswitch-to-headset-profile true` restores/enables that native behavior. Manual mode selection remains available. Each explicit selection routes playback to the current AirPods sink; automatic reconnect routing requires legacy watcher enforcement. Discover PipeWire IDs and available codecs dynamically; prefer A2DP SBC-XQ for Music and best enumerated HFP (LC3, mSBC, CVSD) for Meeting.
- Watcher defaults to no profile or default-output changes, even with saved enabled policy and desired Meeting intent. Stop/disable any old watcher with `systemctl --user disable --now gnome-airpods-companion.service`. `policy enable` disables WirePlumber autoswitch only; it does not enable background enforcement. Legacy enforcement is a separate `watch --enforce-profiles` opt-in requiring policy ownership. Never explicitly change Ubuntu's default microphone when changing audio mode. Profile selection is distinct from default-output routing, and a disappearing source can independently cause the audio server to choose a microphone fallback; disclose this.
- Optional Voxtype integration: follow current Ubuntu default microphone by default, with a user-selectable pinned input. Do not confuse ALSA names with PipeWire node names. Do not interrupt an active recording for configuration changes.
- Connection controls, real current versus desired profile, per-bud/case battery with unavailable/stale indications, supported ANC/transparency/adaptive modes, conversation awareness, one-bud ANC and ear-detection behavior.
- Reuse audited, pinned LibrePods protocol work rather than reimplement proprietary packets. Do not allow the upstream daemon's playback activation policy to fight Meeting mode.
- Native GNOME appearance and workflow; no desktop replacement or GUI automation. Per-user installation, backup, explicit enable/disable and uninstall; preserve unrelated configuration and human edits.
- No audio recording or live audio interruptions without coordinated user check-in. No real hardware data, names, MACs, pairing secrets or logs in the public repository.

## Local component contract

Executable installed as `~/.local/bin/gnome-airpods-companion` (Python3 stdlib backend). CLI commands:

- `status`: JSON object, read-only. Keys `schema_version:1`, `connected:bool`, `device_name:string|null`, `desired_mode:"music"|"meeting"|null`, `active_profile:string|null`, `error:string|null`, `microphones:[{name,description}]`, `voxtype:{mode:"default"|"pinned",source:string|null}`, `apple:{available:bool,...}`. Apple schema should normalize available battery/capabilities/control state, not fabricate it. Additional keys allowed.
- `mode music|meeting`: persist and select profile without setting global default source.
- `connect`, `disconnect`: selected known paired AirPods only, do not pair/forget automatically.
- `voxtype default` or `voxtype pin NODE_NAME`: set optional dictation routing independently of global default input.
- `apple VERB`: validated delegation to pinned librepods-ctl; verbs must come from actual inspected upstream API. UI should use only explicitly provided supported controls.
- `watch`: user-service mode, bounded retries, no permanent busy profile-fighting loop.

The frontend must spawn asynchronously with argv arrays, handle errors and stale/missing data, avoid unbounded processes, and clean up all signals/timers on disable. Preferred UI: top-bar panel menu, full details and settings via menu/submenus.

## Acceptance gates

Automated tests in vertical RED/GREEN slices; independent security/logic review; no placeholders passed off as hardware results. Real GNOME load, mode readback, reconnect persistence, actual ANC/battery readback, user-confirmed dictation and Meet, and uninstall/restore checks before declaring complete. If a logout or physical interaction is required, ask the user rather than automating their desktop.

## Status

Implementation in progress, not released or hardware-verified.
