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
        constructor(label) { this.label = label; this.signals = new Map(); this.sensitive = true; }
        connect(name, callback) { const id = ++serial; this.signals.set(id, {name, callback}); return id; }
        disconnect(id) { this.signals.delete(id); }
        setSensitive(value) { this.sensitive = value; }
        setOrnament() {}
        destroy() { this.signals.clear(); this.destroyed = true; }
    }
    class Menu extends Item {
        constructor() { super(); this.items = []; }
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
        constructor(label) { super(label); this.menu = new Menu(); }
        destroy() { this.menu.destroy(); super.destroy(); }
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
    const context = vm.createContext({...model,Gio,GLib,St:{Icon:class {}},Extension:class {uuid='gnome-airpods-companion@dosment.github.io';},
        Main:{panel:{addToStatusArea() {}}},PanelMenu:{Button},PopupMenu:{PopupMenuItem:Item,PopupSubMenuMenuItem:Submenu,PopupSeparatorMenuItem:Item,Ornament:{DOT:1}}});
    vm.runInContext(text.replace(/^import .*;\n/gm,'').replace('export default class','class') + '\nglobalThis.ExtensionUnderTest = AirPodsCompanionExtension;',context);
    const extension = new context.ExtensionUnderTest();
    extension.enable();
    return {extension, controller:extension._companion,timers,processes};
}

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
    const command = h.controller.act('mode','music');
    assert.deepEqual(Array.from(h.processes[1].argv).slice(1),['mode','music']);
    h.processes[1].finish('',1,'test rejection');
    await tick();
    assert.equal(h.controller.error,'test rejection');
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
    const submenu = h.controller.button.menu.items.find(item => item.label === 'Voxtype microphone');
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
    const mic = items.find(item => item.label === 'Voxtype microphone').menu.items.map(item => item.label).join('\n');
    assert.match(mic,/Desired: Pinned: new.mic/);
    assert.match(mic,/Effective launch: Ubuntu default input/);
    assert.match(mic,/Wrapper: running/);
    assert.match(mic,/restart required/i);
    assert.match(mic,/capture not verified/i);
    assert.doesNotMatch(mic,/until active dictation finishes/);
    assert.ok(items.some(item => /Conversation Awareness · Reported: On/.test(item.label)));
    assert.ok(items.some(item => /One-Bud ANC · Reported: On/.test(item.label)));
    assert.ok(items.some(item => /Adaptive noise level · Reported: 40/.test(item.label)));
    assert.ok(items.some(item => /Ear detection · Local policy:/.test(item.label)));
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
