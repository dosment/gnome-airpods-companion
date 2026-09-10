// SPDX-License-Identifier: GPL-3.0-or-later
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {parseStatus, commandArgs, canAct, checkReply, safeText, popupPresentation} from './model.js';

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
        if (this.closed || !canAct(action, value, this.status, {
            stale: this.stale, changing: this.changing, pending: Boolean(this.pending),
        })) return;
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

    row(menu, text, styleClass = '') {
        const row = new PopupMenu.PopupMenuItem(safeText(text), {reactive: false, can_focus: false, style_class: styleClass || null});
        menu.addMenuItem(row);
        return row;
    }

    batteryGrid(menu, columns) {
        const grid = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false, style_class: 'airpods-battery-grid'});
        grid.label = columns.map(column => `${column.label} · ${column.text}`).join(' | '); // Testable accessible summary.
        for (const column of columns) {
            const cell = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'airpods-battery-cell'});
            const unavailable = column.text === '—';
            cell.add_child(new St.Icon({icon_name: this.batteryIcon(column.text), style_class: `airpods-battery-icon${unavailable ? ' airpods-battery-icon-unavailable' : ''}`}));
            cell.add_child(new St.Label({text: column.label, style_class: 'airpods-battery-label'}));
            cell.add_child(new St.Label({text: column.text, style_class: `airpods-battery-value${unavailable ? ' airpods-battery-value-unavailable' : ''}`}));
            grid.add_child(cell);
        }
        menu.addMenuItem(grid);
        return grid;
    }

    batteryIcon(text) {
        const level = Number.parseInt(text, 10);
        if (!Number.isInteger(level) || level < 0 || level > 100) return 'battery-missing-symbolic';
        if (level >= 95) return 'battery-full-symbolic';
        return `battery-level-${Math.max(0, Math.min(90, Math.ceil(level / 10) * 10))}-symbolic`;
    }

    segments(menu, options, action, title) {
        const group = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false, style_class: 'airpods-segment-group'});
        group.label = title;
        const box = new St.BoxLayout({x_expand: true, style_class: 'airpods-segments'});
        for (const option of options) {
            const enabled = option.enabled === true && !this.pending && !this.changing && !this.stale;
            const selected = option.selected === true;
            const button = new St.Button({
                toggle_mode: true,
                checked: selected,
                reactive: enabled,
                can_focus: enabled,
                x_expand: true,
                style_class: `airpods-segment${selected ? ' airpods-segment-selected' : ''}${enabled ? '' : ' airpods-segment-disabled'}`,
                accessible_name: `${safeText(option.label)}${selected ? ', selected' : ''}`,
            });
            const content = new St.BoxLayout({x_expand: true, style_class: 'airpods-segment-content'});
            content.add_child(new St.Icon({icon_name: option.icon || 'audio-speakers-symbolic', style_class: 'airpods-segment-icon'}));
            content.add_child(new St.Label({text: safeText(option.label), style_class: 'airpods-segment-label'}));
            // St.Button inherits St.Bin: it owns one child, so put the icon/label row in a box.
            button.set_child(content);
            if (enabled) button.connect('clicked', () => {
                // Toggle-mode clicks mutate checked before this signal; restore observed state until readback.
                button.checked = selected;
                this.act(action, option.argv[1]);
            });
            box.add_child(button);
        }
        group.add_child(box);
        menu.addMenuItem(group);
        return group;
    }

    action(menu, label, action, value = null, selected = false, styleClass = '', enabled = null, icon = null) {
        const row = icon
            ? new PopupMenu.PopupImageMenuItem(safeText(label), icon, {style_class: styleClass || null})
            : new PopupMenu.PopupMenuItem(safeText(label), {style_class: styleClass || null});
        if (selected) row.setOrnament(PopupMenu.Ornament.DOT);
        const allowed = enabled ?? canAct(action, value, this.status, {
            stale: this.stale, changing: this.changing, pending: Boolean(this.pending),
        });
        row.setSensitive(allowed);
        row.connect('activate', () => this.act(action, value));
        menu.addMenuItem(row);
        return row;
    }

    submenu(parent, label, icon = null) {
        const row = new PopupMenu.PopupSubMenuMenuItem(safeText(label), Boolean(icon));
        if (icon) row.icon.icon_name = icon;
        parent.addMenuItem(row);
        return row.menu;
    }

    render() {
        if (this.closed) return;
        const menu = this.button.menu;
        menu.removeAll();
        const view = popupPresentation(this.status, {stale: this.stale, changing: this.changing, error: this.error});
        if (view.notice) this.row(menu, view.notice, `airpods-notice${this.error ? ' airpods-notice-error' : ''}`);
        this.row(menu, view.header.title, 'airpods-title');
        this.row(menu, view.header.connection, 'airpods-connection');
        if (view.disconnectedHint) this.row(menu, view.disconnectedHint, 'airpods-section-description');
        if (view.battery) this.batteryGrid(menu, view.battery.columns);

        if (view.audioMode) {
            this.row(menu, 'Audio mode', 'airpods-section-title');
            this.segments(menu, view.audioMode.options, 'mode', 'Audio mode');
            this.row(menu, view.audioMode.description, 'airpods-section-description');
            if (view.audioMode.pendingHint) this.row(menu, view.audioMode.pendingHint, 'airpods-section-description');
        }

        if (view.noiseControl) {
            this.row(menu, 'Noise control', 'airpods-section-title');
            this.segments(menu, view.noiseControl.options, 'apple', 'Noise control');
        }

        const mic = this.submenu(menu, `Dictation mic · ${view.dictation.summary}`, 'microphone-sensitivity-high-symbolic');
        for (const option of view.dictation.items)
            this.action(mic, option.label, option.argv[0] === 'voxtype' && option.argv[1] === 'pin' ? 'voxtype-pin' : 'voxtype-default', option.argv[2] ?? null, option.selected);

        const settings = this.submenu(menu, 'More settings', 'emblem-system-symbolic');
        const apple = this.status?.apple ?? {};
        const state = apple.state ?? {};
        for (const item of view.moreSettings.items) {
            if (item.id === 'diagnostics') continue;
            const sub = this.submenu(settings, item.label);
            if (item.action === 'ca' || item.action === 'onebud') {
                const key = item.action === 'ca' ? 'conversation_awareness' : 'one_bud_anc';
                const verb = item.action === 'ca' ? 'ca' : 'onebud';
                this.action(sub, 'On', 'apple', `${verb}:on`, state[key] === true);
                this.action(sub, 'Off', 'apple', `${verb}:off`, state[key] === false);
            } else if (item.action === 'ear') {
                for (const [key, label] of Object.entries(EAR)) this.action(sub, label, 'apple', `ear:${key}`, state.ear_detection === key);
            } else if (item.action === 'adaptive') {
                for (const level of [0, 25, 50, 75, 100]) this.action(sub, `${level}%`, 'apple', `adaptive:${level}`, state.adaptive_level === level);
            }
        }
        const diagnostics = this.submenu(settings, 'Diagnostics');
        for (const line of view.diagnostics) {
            if (line === 'Refresh status') {
                const refresh = new PopupMenu.PopupMenuItem(line);
                refresh.setSensitive(!this.pending && !this.changing);
                refresh.connect('activate', () => this.refresh());
                diagnostics.addMenuItem(refresh);
            } else this.row(diagnostics, line, 'airpods-diagnostic-line');
        }
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.action(menu, view.footer.label, view.footer.action, null, false,
            view.footer.action === 'connect' ? 'airpods-connect' : '', view.footer.enabled,
            view.footer.action === 'disconnect' ? 'network-disconnect-symbolic' : 'network-connect-symbolic');
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
