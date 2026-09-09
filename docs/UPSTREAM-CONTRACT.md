# Pinned daemon IPC contract

Source of truth: `daemon/main.cpp:1698-1803, 2025-2164`,
`daemon/librepods-ctl.cpp`, `daemon/enums.h`, `daemon/deviceinfo.hpp`, and
`daemon/ble/blemanager.cpp` at `fff7fec600a5b9a61cdb40e93eccbcceb4b8f824`.
These are inspected source facts, not fabricated live device output.

## Transport and freshness

Run `librepods --headless` only after installation/service review and an audio
interruption check-in. Invoke controls as an argv array:
`[absolute_ctl_path, verb]`. This is a separate program from the upstream
`openpods` application name; actual build target/binary is `librepods-ctl`.

`librepods-ctl status` prints one compact JSON line, schema_version 1, using
`$XDG_RUNTIME_DIR/librepods.sock`. Client budgets: connect 500 ms, write 500 ms,
reply 1000 ms; an outer timeout around 3 seconds is appropriate. Exit 1 means
connection/reply failure; exit 0 on **control verbs is only submission**, not
hardware acknowledgement. Unsupported verbs can also exit 0. Validate verbs
and capabilities before invocation; poll/readback separately with bounded retry.
The status client reads one available chunk, not a fully framed streaming JSON
parser, so reject truncated/invalid JSON rather than inventing defaults.

Equivalent state file:
`${XDG_STATE_HOME:-$HOME/.local/state}/librepods/status.json`. A one-second
writer checks state and atomically replaces the file **only when content
changes**. It removes it on graceful quit, but SIGKILL/crash can leave stale
files. File mtime is **not a heartbeat nor a per-battery observation time**:
a healthy stable state can be old. Prefer a successful socket status request
to establish daemon liveness; expose unknown battery freshness because neither
transport gives timestamps for individual observations.

`connected` means the daemon's proprietary AAP **control** L2CAP socket is
connected, **not** BlueZ audio-profile connectivity. The companion must derive
Bluetooth/audio connectivity and actual profile separately. BLE battery may
remain available while control socket is disconnected.

## Status fields

| Field | Type / meaning |
|---|---|
| `schema_version` | integer 1; reject incompatible versions |
| `connected` | boolean AAP control socket connected |
| `device_name` | string, possibly empty; private identity |
| `noise_mode` | integer: 0 Off, 1 ANC, 2 Transparency, 3 Adaptive; -1 fallback unknown |
| `left`, `right` | objects `{available:bool, level:int, charging:bool, in_ear:bool}` |
| `case`, `headset` | objects `{available:bool, level:int, charging:bool}` |
| `conversational_awareness` | boolean (note spelling; not `conversation_awareness`) |
| `adaptive_noise_level` | integer 0–100 |
| `one_bud_anc_mode` | boolean |
| `ear_detection_behavior` | integer: 0 pause when either removed; 1 when both removed; 2 disabled |
| `lid_state` | integer: 0 open, 1 closed, 2 unknown |
| `model_name`, `model_number` | strings; model_number is the A-number, not a MAC |
| `model_int` | persisted enum integer; use capability booleans instead of hardcoding it |
| `is_pro_series`, `is_headset` | booleans; neither substitutes for capabilities |
| `supports_noise_control`, `supports_noise_off` | booleans |
| `supports_adaptive`, `supports_conversational_awareness`, `supports_one_bud_anc` | booleans |

Battery objects are conditional on a battery object existing; accept missing
objects and `available:false` and never turn unavailable/sentinel levels into
0% or 100%. Only display available integer levels in [0,100]. Default values
and saved preferences exist before observations arrive; control connectivity
alone does not prove that every state field is freshly read from hardware.
No active audio profile, default microphone, observation timestamp or device
MAC is published in this schema.

Additional process-lifetime telemetry keys:
`reconnect_attempts_total`, `reconnect_failures_total`,
`noise_control_changes_total`, `forget_calls_total`,
`ear_detection_changes_total`, `ca_changes_total`, `disconnect_calls_total`,
`connect_calls_total`, `disconnect_failures_total`, `connect_failures_total`,
`adaptive_level_changes_total`, `one_bud_anc_changes_total`, `reopen_calls_total`.
Treat extra additive keys as ignorable; do not make UI depend on JSON key order.

## Controls safe to expose through a validated Apple-control API

| Verb | Gate / behavior |
|---|---|
| `noise:off` | connected + supports_noise_control + supports_noise_off |
| `noise:anc`, `noise:transparency` | connected + supports_noise_control |
| `noise:adaptive` | connected + supports_adaptive |
| `ca:on`, `ca:off` | connected + supports_conversational_awareness |
| `onebud:on`, `onebud:off` | connected + supports_one_bud_anc |
| `adaptive:N` | integer N 0–100, supports_adaptive and noise_mode == 3; otherwise ignored |
| `ear:one`, `ear:both`, `ear:off` | daemon-local persisted pause/resume policy; no hardware ANC capability gate |

For this pinned integration, missing/invalid capability keys mean **unknown,
do not offer the control**. Do not inherit Omarchy's legacy permissive fallback
that treats all Pro-series devices as supporting adaptive/CA; AirPods 4 ANC
is not Pro-series and nevertheless supports these features. `noise:cycle`
exists but explicit modes allow safer capability gating.

Other upstream verbs: `connect`, `disconnect` launch `bluetoothctl` against
the daemon's remembered/current device; `forget` removes its BlueZ pairing;
`reopen` is refused by headless daemon. Do not include `forget` or `reopen`
in the companion Apple verb whitelist. Prefer the companion's explicit known-
paired selected-device logic for connect/disconnect; the upstream daemon
stores only one current identity, not a user-selected multi-device contract.

### Readback is not universally confirmed state

- Noise mode setter sends a packet without immediately changing model state;
  noise notifications update it later. Still, startup defaults and missing
  observation timestamps mean a displayed initial value can be unconfirmed.
- CA setter changes its model boolean even if writing the packet failed
  (`main.cpp:450-466`). Adaptive level does likewise while Adaptive is active
  (`514-523`). One-bud ANC updates after socket-open/write submission but
  does not wait for hardware acknowledgement (`469-489`).
- CA, one-bud and adaptive values are also loaded from QSettings. **A later
  matching status value is not proof that hardware accepted these controls.**
  Label them daemon-reported/requested or confirmation-unknown; do not report
  “hardware verified” based on these values. A future protocol/observation
  enhancement is needed for strict actual-versus-desired confirmation.
- Ear behavior is local application policy; status is an authoritative report
  of that policy, not a switch for the earbuds' hardware sensors.

## AirPods 4 with ANC

The exact pin maps A3055/A3056/A3057 to `AirPods4ANC`, and BLE product ID
`0x1B20` to that enum. Its `model_name` is simply **AirPods 4**, identical to
non-ANC AirPods 4; do not identify ANC capability from display text.
Capabilities return true for noise control, noise off, adaptive audio,
Conversation Awareness and one-bud ANC. Both battery parsing paths and local
ear-detection policy are present. This establishes **source support**, not
successful behavior on the user's physical pair; all controls and reconnect
behavior remain hardware acceptance gates.
