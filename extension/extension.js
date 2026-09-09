// SPDX-License-Identifier: GPL-3.0-or-later
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {parseStatus, batteryText, commandArgs, checkReply, safeText} from './model.js';

const NOISE = {off: 'Off', anc: 'Noise Cancellation', transparency: 'Transparency', adaptive: 'Adaptive'};
const EAR = {one: 'Pause when one is out', both: 'Pause when both are out', off: 'Never pause'};

// A controller per enable cycle prevents old async callbacks from mutating a new UI.
class CompanionMenu {
    constructor(uuid) {
        this.closed = false;
        this.pending = null;
        this.status = null;
        this.error = '';
        this.stale = false;
        this.snapshot = null;
        this.binary = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'gnome-airpods-companion']);
        this.button = new PanelMenu.Button(0.0, 'AirPods Companion');
        this.button.add_child(new St.Icon({icon_name: 'audio-headphones-symbolic', style_class: 'system-status-icon'}));
        Main.panel.addToStatusArea(uuid, this.button);
        this.menuSignal = this.button.menu.connect('open-state-changed', (_menu, open) => {
            if (open) this.refresh();
        });
        this.render();
        this.poll = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
            this.refresh();
            return GLib.SOURCE_CONTINUE;
        });
        this.refresh();
    }

    // One subprocess maximum, argv only, cancellable and bounded even if the backend hangs.
    run(args) {
        if (this.closed || this.pending) return Promise.reject(new Error('Companion is busy'));
        return new Promise((resolve, reject) => {
            const job = {process: null, cancellable: new Gio.Cancellable(), timeout: 0, timedOut: false};
            try {
                job.process = Gio.Subprocess.new([this.binary, ...args],
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
                this.pending = job;
                job.timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 15, () => {
                    job.timeout = 0;
                    job.timedOut = true;
                    job.cancellable.cancel();
                    job.process.force_exit();
                    return GLib.SOURCE_REMOVE;
                });
                job.process.communicate_utf8_async(null, job.cancellable, (process, result) => {
                    if (job.timeout) GLib.Source.remove(job.timeout);
                    job.timeout = 0;
                    if (this.pending === job) this.pending = null;
                    try {
                        const [, stdout, stderr] = process.communicate_utf8_finish(result);
                        if (job.timedOut) throw new Error('Companion timed out');
                        const exitCode = process.get_if_exited() ? process.get_exit_status() : -1;
                        resolve(checkReply(exitCode, stdout, stderr, args[0] === 'status'));
                    } catch (error) {
                        reject(job.timedOut ? new Error('Companion timed out') : error);
                    }
                });
            } catch (error) {
                if (job.timeout) GLib.Source.remove(job.timeout);
                job.cancellable.cancel();
                job.process?.force_exit();
                if (this.pending === job) this.pending = null;
                reject(error);
            }
        });
    }

    async refresh() {
        if (this.closed || this.pending || this.changing) return;
        try {
            const raw = await this.run(['status']);
            if (this.closed) return;
            const status = parseStatus(raw);
            // Snapshot age is diagnostic, not rendered; do not destroy open menus each poll.
            const snapshot = JSON.stringify(status, (key, value) => key === 'age_seconds' ? undefined : value);
            const changed = snapshot !== this.snapshot || this.stale;
            this.status = status;
            this.snapshot = snapshot;
            this.stale = false;
            // Keep command errors until next explicit action, not merely a successful poll.
            if (this.statusError) { this.error = ''; this.statusError = false; }
            if (changed) this.render();
        } catch (error) {
            if (this.closed) return;
            this.error = safeText(error.message);
            this.statusError = true;
            this.stale = true;
            this.render();
        }
    }

    async act(action, value = null) {
        if (this.closed || this.pending || this.changing || this.stale) return;
        try {
            const args = commandArgs(action, value, this.status);
            this.changing = true;
            this.error = '';
            const result = this.run(args);
            this.render();
            await result;
        } catch (error) {
            if (!this.closed) this.error = safeText(error.message);
        } finally {
            this.changing = false;
            if (!this.closed) {
                this.render();
                await this.refresh();
            }
        }
    }

    row(menu, text) {
        const row = new PopupMenu.PopupMenuItem(safeText(text), {reactive: false, can_focus: false});
        menu.addMenuItem(row);
        return row;
    }

    action(menu, label, action, value = null, selected = false) {
        const row = new PopupMenu.PopupMenuItem(safeText(label));
        if (selected) row.setOrnament(PopupMenu.Ornament.DOT);
        let enabled = !this.pending && !this.changing && !this.stale;
        try { commandArgs(action, value, this.status); } catch { enabled = false; }
        row.setSensitive(enabled);
        row.connect('activate', () => this.act(action, value));
        menu.addMenuItem(row);
        return row;
    }

    submenu(label) {
        const row = new PopupMenu.PopupSubMenuMenuItem(safeText(label));
        this.button.menu.addMenuItem(row);
        return row.menu;
    }

    render() {
        if (this.closed) return;
        const menu = this.button.menu;
        menu.removeAll();
        const status = this.status;
        this.row(menu, status?.device_name || 'AirPods Companion');
        this.row(menu, this.stale ? 'Status unavailable · Last reading is stale' :
            status ? (status.connected ? 'Connected' : 'Disconnected') : 'Reading companion status…');
        if (this.error) this.row(menu, `Error: ${this.error}`);
        if (status?.error) this.row(menu, `Backend: ${status.error}`);
        if (this.changing) this.row(menu, 'Applying… Waiting for status readback');
        if (status) {
            this.action(menu, status.connected ? 'Disconnect' : 'Connect', status.connected ? 'disconnect' : 'connect');
            const audio = this.submenu('Audio mode');
            this.row(audio, `Desired: ${status.desired_mode === 'music' ? 'Music' : status.desired_mode === 'meeting' ? 'Meeting' : 'Not selected'}`);
            this.row(audio, `Current profile: ${status.active_profile || 'Unavailable'}`);
            this.action(audio, 'Music · High-quality playback', 'mode', 'music', status.desired_mode === 'music');
            this.action(audio, 'Meeting · Headset microphone', 'mode', 'meeting', status.desired_mode === 'meeting');
            this.row(audio, 'Modes never set Ubuntu’s default microphone.');
            this.row(audio, 'An unavailable source may trigger Ubuntu fallback.');
            this.row(audio, 'Meeting reduces Bluetooth playback quality.');

            const vox = status.voxtype ?? {};
            const mic = this.submenu('Voxtype microphone');
            this.row(mic, vox.mode === 'pinned' ? `Desired: Pinned: ${vox.source || 'Unavailable'}` : 'Desired: Ubuntu default input');
            this.row(mic, `Effective launch: ${vox.effective ? (vox.effective.mode === 'pinned' ? vox.effective.source : 'Ubuntu default input') : 'Unknown'}`);
            this.row(mic, `Wrapper: ${vox.integration === 'wrapper_running' ? 'running' : vox.integration === 'stale_receipt' ? 'stale receipt · integration unknown' : 'integration unknown'}`);
            this.action(mic, 'Follow Ubuntu default input', 'voxtype-default', null, vox.mode !== 'pinned');
            const sources = Array.isArray(status.microphones) ? status.microphones : [];
            for (const source of sources) {
                if (typeof source?.name !== 'string' || !source.name) continue;
                this.action(mic, source.description || source.name, 'voxtype-pin', source.name,
                    vox.mode === 'pinned' && vox.source === source.name);
            }
            if (vox.mode === 'pinned' && !sources.some(source => source?.name === vox.source))
                this.row(mic, 'Pinned input is currently unavailable');
            if (sources.length === 0) this.row(mic, 'No microphone sources reported');
            this.row(mic, 'Independent of Ubuntu’s default input.');
            this.row(mic, vox.pending_restart !== false ? 'Coordinated idle restart required via voxtype-run.' : 'Launch matches desired routing.');
            this.row(mic, 'Changes require an explicit idle restart; no automatic restart.');
            this.row(mic, 'Actual capture not verified.');

            const apple = status.apple ?? {};
            const battery = this.submenu('Battery');
            const parts = apple.is_headset === true ? [['headset', 'Headphones']] : [['left', 'Left'], ['right', 'Right'], ['case', 'Case']];
            for (const [key, label] of parts)
                this.row(battery, `${label}: ${batteryText(apple.battery?.[key], this.stale || !status.connected || apple.available !== true || apple.stale === true)}`);
            if (apple.available !== true) this.row(menu, 'Apple telemetry unavailable');
            if (apple.stale === true) this.row(menu, 'Apple telemetry stale · Controls disabled');
            if (apple.error) this.row(menu, `Apple: ${apple.error}`);
            const cap = apple.capabilities ?? {};
            const state = apple.state ?? {};
            const modes = Array.isArray(cap.noise_modes) ? cap.noise_modes.filter(mode => Object.hasOwn(NOISE, mode)) : [];
            if (modes.length) {
                const listening = this.submenu(`Listening · ${NOISE[state.noise_mode] || 'Unknown'}`);
                for (const mode of modes) this.action(listening, NOISE[mode], 'apple', `noise:${mode}`, state.noise_mode === mode);
            }
            if (cap.adaptive_level === true && state.noise_mode === 'adaptive') {
                const level = this.submenu(`Adaptive noise level · Reported: ${Number.isInteger(state.adaptive_level) ? state.adaptive_level : 'Unknown'}`);
                for (const n of [0, 25, 50, 75, 100])
                    this.action(level, `${n}%`, 'apple', `adaptive:${n}`, state.adaptive_level === n);
            }
            for (const [capability, key, verb, label] of [
                ['conversation_awareness', 'conversation_awareness', 'ca', 'Conversation Awareness'],
                ['one_bud_anc', 'one_bud_anc', 'onebud', 'One-Bud ANC'],
            ]) {
                if (cap[capability] !== true) continue;
                const toggle = this.submenu(`${label} · Reported: ${state[key] === true ? 'On' : state[key] === false ? 'Off' : 'Unknown'}`);
                this.action(toggle, 'On', 'apple', `${verb}:on`, state[key] === true);
                this.action(toggle, 'Off', 'apple', `${verb}:off`, state[key] === false);
            }
            if (cap.ear_detection === true) {
                const ear = this.submenu(`Ear detection · Local policy: ${EAR[state.ear_detection] || 'Unknown'}`);
                for (const [key, label] of Object.entries(EAR))
                    this.action(ear, label, 'apple', `ear:${key}`, state.ear_detection === key);
            }
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const refresh = new PopupMenu.PopupMenuItem('Refresh status');
        refresh.setSensitive(!this.pending && !this.changing);
        refresh.connect('activate', () => this.refresh());
        menu.addMenuItem(refresh);
    }

    destroy() {
        this.closed = true;
        if (this.poll) GLib.Source.remove(this.poll);
        this.poll = 0;
        if (this.pending) {
            if (this.pending.timeout) GLib.Source.remove(this.pending.timeout);
            this.pending.timeout = 0;
            this.pending.cancellable.cancel();
            this.pending.process.force_exit();
            this.pending = null;
        }
        this.button.menu.disconnect(this.menuSignal);
        this.button.destroy(); // Destroys menu items and their activation signals.
        this.button = null;
    }
}

export default class AirPodsCompanionExtension extends Extension {
    enable() { this._companion = new CompanionMenu(this.uuid); }
    disable() {
        this._companion?.destroy();
        this._companion = null;
    }
}
