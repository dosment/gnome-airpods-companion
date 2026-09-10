// SPDX-License-Identifier: GPL-3.0-or-later
// Controller contract tests with GNOME/Gio fakes; NOT a real Shell loading test.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import * as model from '../extension/model.js';

const text = readFileSync(new URL('../extension/extension.js', import.meta.url), 'utf8');
const fixture = JSON.stringify({schema_version:1, connected:false, desired_mode:'meeting', active_profile:null,
    microphones:[], voxtype:{mode:'default',source:null}, apple:{available:false}});
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness() {
    let serial = 0;
    const timers = new Map();
    const processes = [];
    class Item {
        constructor(label) { this.label = label; this.signals = new Map(); this.sensitive = true; this.children = []; }
        add_child(child) { this.children.push(child); }
        get_children() { return [...this.children]; }
        insert_child_below(child, sibling) {
            const index = this.children.indexOf(sibling);
            if (index < 0) throw new Error('sibling must be a native child');
            this.children.splice(index, 0, child);
        }
        connect(name, callback) { const id = ++serial; this.signals.set(id, {name, callback}); return id; }
        disconnect(id) { this.signals.delete(id); }
        setSensitive(value) { this.sensitive = value; }
        add_style_class_name(name) { this.style_class = `${this.style_class || ''} ${name}`.trim(); }
        setOrnament(value) { this.ornament = value; }
        destroy() { this.signals.clear(); this.destroyed = true; }
    }
    class Menu extends Item {
        constructor() { super(); this.items = []; this.box = new Item(); }
        addMenuItem(item) { this.items.push(item); }
        removeAll() { this.items.forEach(item => item.destroy()); this.items = []; }
        destroy() { this.removeAll(); super.destroy(); }
    }
    class Button extends Item {
        constructor() { super(); this.menu = new Menu(); }
        add_child() {}
        destroy() { this.menu.destroy(); super.destroy(); }
    }
    class Submenu extends Item {
        constructor(label, wantIcon = false) {
            super(label);
            this.wantIcon = wantIcon;
            this.icon = wantIcon ? new Icon() : null;
            if (this.icon) this.add_child(this.icon);
            this.nativeLabel = new Label({text: label, y_expand: true});
            // GNOME Shell 50.1's native PopupSubMenuMenuItem owns this expanding
            // bin between its label and triangle; it is not exposed as a field.
            this.nativeExpander = new StBin({x_expand: true, style_class: 'popup-menu-item-expander'});
            this._triangleBin = new StBin({y_expand: true});
            this.add_child(this.nativeLabel);
            this.add_child(this.nativeExpander);
            this.add_child(this._triangleBin);
            this.menu = new Menu();
        }
        destroy() { this.menu.destroy(); super.destroy(); }
    }
    class SwitchMenuItem extends Item {
        constructor(label, state, params = {}) { super(label); this.state = state; Object.assign(this, params); }
        setToggleState(state) { this.state = state; }
    }
    const Gio = {
        Cancellable: class { cancel() { this.cancelled = true; } },
        SubprocessFlags:{STDOUT_PIPE:1,STDERR_PIPE:2},
        Subprocess:{new(argv) {
            const process = {
                argv, exit:0, stdout:'', stderr:'', killed:false,
                communicate_utf8_async(_input, cancellable, callback) { this.cancellable = cancellable; this.callback = callback; },
                communicate_utf8_finish() { if (this.cancellable.cancelled) throw new Error('Cancelled'); return [true,this.stdout,this.stderr]; },
                get_if_exited() { return true; }, get_exit_status() { return this.exit; },
                force_exit() { this.killed = true; },
                finish(stdout = '', exit = 0, stderr = '') { Object.assign(this,{stdout,exit,stderr}); this.callback(this, {}); },
            };
            processes.push(process);
            return process;
        }},
    };
    const GLib = {PRIORITY_DEFAULT:0,SOURCE_CONTINUE:true,SOURCE_REMOVE:false,
        get_home_dir:() => '/test-home',build_filenamev:parts => parts.join('/'),
        timeout_add_seconds(_priority,seconds,callback) { const id = ++serial; timers.set(id,{seconds,callback}); return id; },
        Source:{remove(id) { timers.delete(id); }}};
    class Box extends Item { constructor(params = {}) { super(); Object.assign(this, params); } }
    class Label extends Item { constructor(params = {}) { super(params.text); Object.assign(this, params); } }
    class StBin extends Item {
        constructor(params = {}) { super(); Object.assign(this, params); }
        get_style_class_name() { return this.style_class || ''; }
        add_child() { throw new Error('St.Bin accepts exactly one child through set_child()'); }
        set_child(child) {
            if (this.child) throw new Error('St.Bin already has a child');
            this.child = child;
        }
    }
    class StButton extends StBin {
        constructor(params = {}) { super(params); this.checked = params.checked === true; this.toggle_mode = params.toggle_mode === true; }
        click() {
            if (this.toggle_mode) this.checked = !this.checked;
            for (const {name, callback} of this.signals.values()) if (name === 'clicked') callback(this);
        }
    }
    class Icon extends Item { constructor(params = {}) { super(); Object.assign(this, params); } }
    class Widget extends Item { constructor(params = {}) { super(); Object.assign(this, params); } }
    const context = vm.createContext({...model,Gio,GLib,Clutter:{ActorAlign:{CENTER:1,END:2}},St:{Icon,Widget,Button:StButton,Bin:StBin,BoxLayout:Box,Label},Extension:class {uuid='gnome-airpods-companion@dosment.github.io';},
        Main:{panel:{addToStatusArea() {}}},PanelMenu:{Button},PopupMenu:{PopupBaseMenuItem:class extends Item { constructor(params = {}) { super(); Object.assign(this, {reactive: params.reactive, can_focus: params.can_focus, style_class: params.style_class}); } },PopupMenuItem:Item,PopupImageMenuItem:class extends Item { constructor(label, icon, params = {}) { super(label); this.icon_name = icon; Object.assign(this, params); } },PopupSwitchMenuItem:SwitchMenuItem,PopupSubMenuMenuItem:Submenu,PopupSeparatorMenuItem:Item,Ornament:{DOT:1}}});
    vm.runInContext(text.replace(/^import .*;\n/gm,'').replace('export default class','class') + '\nglobalThis.ExtensionUnderTest = AirPodsCompanionExtension;',context);
    const extension = new context.ExtensionUnderTest();
    extension.enable();
    return {extension, controller:extension._companion,timers,processes};
}

test('stylesheet scopes the reference panel while retaining Shell native switches and focus styles', () => {
    const css = readFileSync(new URL('../extension/stylesheet.css', import.meta.url), 'utf8');
    assert.match(css, /\.airpods-popup \{[\s\S]*width: 443px[\s\S]*background-color: #151515[\s\S]*border: 1px solid #d8754f/);
    assert.match(css, /font-family: "Ubuntu Sans Mono", monospace/);
    assert.match(css, /\.airpods-battery-track[\s\S]*width: 220px[\s\S]*height: 7px/);
    assert.match(css, /\.airpods-popup \.toggle-switch[\s\S]*width: 42px/);
    assert.match(css, /\.airpods-listening-selected[\s\S]*font-weight: 700/);
    assert.match(css, /\.airpods-segment:focus[\s\S]*border: 2px solid/);
});


test('controller uses absolute argv, prevents overlap, and cancels everything on disable', async () => {
    const h = harness();
    assert.deepEqual(Array.from(h.processes[0].argv), ['/test-home/.local/bin/gnome-airpods-companion','status']);
    await h.controller.refresh();
    assert.equal(h.processes.length,1);
    const button = h.controller.button;
    h.extension.disable();
    assert.equal(h.timers.size,0);
    assert.equal(h.processes[0].killed,true);
    assert.equal(h.processes[0].cancellable.cancelled,true);
    assert.equal(button.destroyed,true);
    h.processes[0].finish(fixture);
    await tick();
    assert.equal(h.extension._companion,null);
});

test('controller preserves last observed status as stale and recovers from command failure', async () => {
    const h = harness();
    h.processes[0].finish(fixture);
    await tick();
    assert.equal(h.controller.status.desired_mode,'meeting');
    const command = h.controller.act('connect');
    assert.deepEqual(Array.from(h.processes[1].argv).slice(1),['connect']);
    h.processes[1].finish('',1,'test rejection');
    await tick();
    assert.equal(h.controller.error,'test rejection');
    assert.equal(h.controller.button.menu.items[0].label, 'Couldn’t apply change');
    const diagnosticLines = h.controller.button.menu.items.find(item => item.label === 'More settings').menu.items.find(item => item.label === 'Diagnostics').menu.items.map(item => item.label);
    assert.ok(diagnosticLines.includes('Error: test rejection'));
    h.processes[2].finish(fixture);
    await command;
    assert.equal(h.controller.status.desired_mode,'meeting');
    const refresh = h.controller.refresh();
    h.processes[3].finish('bad JSON');
    await refresh;
    assert.equal(h.controller.stale,true);
    await h.controller.act('connect');
    assert.equal(h.processes.length,4);
    h.extension.disable();
});

test('polling a different snapshot age preserves open submenu objects', async () => {
    const h = harness();
    const state = JSON.parse(fixture);
    state.apple.age_seconds = 10;
    h.processes[0].finish(JSON.stringify(state));
    await tick();
    const submenu = h.controller.button.menu.items.find(item => item.label === 'More settings');
    state.apple.age_seconds = 15;
    const poll = h.controller.refresh();
    h.processes[1].finish(JSON.stringify(state));
    await poll;
    assert.equal(submenu.destroyed, undefined);
    assert.ok(h.controller.button.menu.items.includes(submenu));
    h.extension.disable();
});

test('routing UI distinguishes desired intent, launch receipt, and explicit restart', async () => {
    const h = harness();
    const state = JSON.parse(fixture);
    state.voxtype = {mode:'pinned',source:'new.mic',effective:{mode:'default',source:null},integration:'wrapper_running',pending_restart:true};
    state.apple = {available:true,capabilities:{conversation_awareness:true,one_bud_anc:true,ear_detection:true,adaptive_level:true},
        state:{noise_mode:'adaptive',conversation_awareness:true,one_bud_anc:true,ear_detection:'one',adaptive_level:40}};
    h.processes[0].finish(JSON.stringify(state));
    await tick();
    const items = h.controller.button.menu.items;
    const more = items.find(item => item.label === 'More settings');
    const micRow = more.menu.items.find(item => item.label === 'Dictation mic');
    const micMenu = micRow.menu.items.map(item => item.label).join('\n');
    assert.ok(micRow);
    assert.doesNotMatch(micMenu,/Effective launch:|Desired routing|capture not verified/i);
    assert.match(more.menu.items.find(item => item.label === 'Diagnostics').menu.items.map(item => item.label).join('\n'), /Desired dictation source: new\.mic/);
    const labels = items.map(item => item.label).join('\n');
    assert.match(labels,/Conversation Awareness/);
    assert.match(labels,/One-Bud ANC/);
    const settings = more.menu.items.map(item => item.label).join('\n');
    assert.match(settings,/Adaptive noise level · 40%/);
    assert.match(labels,/Ear detection/);
    assert.doesNotMatch(settings,/Reported:|Local policy:|Select Adaptive/);
    h.extension.disable();
});

test('compact popup renders native horizontal segments, symbolic batteries, and disconnect footer', async () => {
    const h = harness();
    const state = JSON.parse(fixture);
    state.connected = true;
    state.device_name = 'My AirPods';
    state.desired_mode = 'music';
    state.active_profile = 'a2dp-sink-sbc_xq';
    state.active_profile_description = 'High Fidelity Playback';
    state.microphones = [{name:'bluez_input.airpods',description:'AirPods microphone'}];
    state.voxtype = {mode:'pinned',source:'bluez_input.airpods',pending_restart:true};
    state.apple = {available:true,capabilities:{noise_modes:['off','anc','transparency','adaptive'],conversation_awareness:true,one_bud_anc:true,ear_detection:true,adaptive_level:true},
        battery:{left:{available:true,level:82},right:{available:true,level:78},case:{available:false}},
        state:{noise_mode:'anc',conversation_awareness:true,one_bud_anc:false,ear_detection:'one'}};
    h.processes[0].finish(JSON.stringify(state));
    await tick();
    const items = h.controller.button.menu.items;
    const labels = items.map(item => item.label);
    assert.deepEqual(labels.slice(0, 6), ['AirPods', 'Battery', 'Left 82%', 'Right 78%', 'Case Unavailable', undefined]);
    assert.ok(labels.includes('Listening mode'));
    assert.ok(labels.includes('Transparency'));
    assert.ok(labels.includes('Adaptive'));
    assert.ok(labels.includes('Noise Cancellation'));
    assert.ok(labels.includes('Conversation Awareness'));
    assert.ok(labels.includes('One-Bud ANC'));
    assert.ok(labels.includes('Ear detection'));
    const ear = items.find(item => item.label === 'Ear detection');
    assert.equal(ear.nativeExpander.child.label, 'Pause when one is out');
    assert.equal(ear.sensitive, true);
    h.controller.stale = true;
    h.controller.render();
    assert.equal(h.controller.button.menu.items.find(item => item.label === 'Ear detection').sensitive, false, 'stale parent submenu is insensitive');
    h.controller.stale = false;
    const change = h.controller.act('apple', 'ear:both');
    assert.equal(h.controller.button.menu.items.find(item => item.label === 'Ear detection').sensitive, false, 'pending parent submenu is insensitive');
    h.processes[1].finish('', 0);
    await tick();
    h.processes[2].finish(JSON.stringify(state));
    await change;
    const settings = h.controller.button.menu.items.find(item => item.label === 'More settings').menu.items.map(item => item.label);
    assert.deepEqual(settings, ['Audio mode', 'Dictation mic', 'Disconnect', 'Diagnostics']);
    assert.equal(labels.includes('Disconnect'), false);
    h.extension.disable();
});

test('battery renderer bounds numeric display levels and preserves unavailable readings', () => {
    const h = harness();
    const menu = h.controller.button.menu;
    menu.removeAll();
    h.controller.batteryRows(menu, [{label:'Left', text:'101%', status:null}, {label:'Right', text:'Unavailable', status:null}]);
    for (const row of menu.items.slice(1)) {
        assert.equal(row.children[1].child, undefined);
        assert.match(row.children[2].style_class, /airpods-unavailable/);
    }
    h.extension.disable();
});

test('audio main menu stays compact while diagnostics retains observed codec detail', async () => {
    const h = harness();
    const state = JSON.parse(fixture);
    state.connected = true;
    state.active_profile = 'headset-head-unit';
    state.active_profile_description = 'Headset Head Unit (HSP/HFP, codec LC3-24kHz)';
    h.processes[0].finish(JSON.stringify(state));
    await tick();
    const items = h.controller.button.menu.items;
    assert.doesNotMatch(items.map(item => item.label).join('\n'),/Headset microphone · reduced playback quality/);
    const audio = items.find(item => item.label === 'More settings').menu.items.find(item => item.label === 'Audio mode').menu.items.map(item => item.label).join('\n');
    assert.match(audio,/Headset microphone · reduced playback quality/);
    assert.doesNotMatch(items.map(item => item.label).join('\n'),/Observed:|Requested .*observed/i);
    const diagnostics = items.find(item => item.label === 'More settings').menu.items.find(item => item.label === 'Diagnostics').menu.items.map(item => item.label).join('\n');
    assert.match(diagnostics,/LC3-24kHz/);
    h.extension.disable();
});

test('retained stale status hides writable listening controls', async () => {
    const h = harness();
    const state = JSON.parse(fixture);
    state.connected = true;
    h.processes[0].finish(JSON.stringify(state));
    await tick();
    const refresh = h.controller.refresh();
    h.processes[1].finish('bad JSON');
    await refresh;
    const labels = h.controller.button.menu.items.map(item => item.label);
    assert.equal(labels.includes('Listening mode'), false);
    assert.equal(labels.includes('Conversation Awareness'), false);
    h.extension.disable();
});

test('controller timeout kills pending process and reports bounded failure', async () => {
    const h = harness();
    const timeout = [...h.timers].find(([,value]) => value.seconds === 15);
    h.timers.delete(timeout[0]);
    timeout[1].callback();
    assert.equal(h.processes[0].killed,true);
    h.processes[0].finish();
    await tick();
    assert.equal(h.controller.error,'Companion timed out');
    assert.equal(h.controller.pending,null);
    h.extension.disable();
    assert.equal(h.timers.size,0);
});
