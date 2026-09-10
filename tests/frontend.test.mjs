// SPDX-License-Identifier: GPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../extension/model.js';
const sample = (extra = {}) => JSON.stringify({schema_version: 1, connected: true, desired_mode: 'music', active_profile: 'a2dp-sink-sbc_xq', microphones: [], voxtype: {mode: 'default', source: null}, apple: {available: false}, ...extra});
test('status rejects malformed, missing and future schemas without exposing controls', () => {
    for (const raw of ['', 'bad', 'null', '[]', '{}', sample({schema_version: 2}), sample({connected: 'yes'})])
        assert.throws(() => model.parseStatus(raw), /status|schema|connected/i);
    assert.equal(model.parseStatus(sample()).desired_mode, 'music');
});

test('battery never invents values and distinguishes stale observations', () => {
    for (const value of [null, {}, {available:false,level:90}, {available:true,level:-1}, {available:true,level:101}, {available:true,level:'50'}])
        assert.equal(model.batteryText(value), 'Unavailable');
    assert.equal(model.batteryText({available:true,level:63,freshness:'unknown'}), '63% · Observation age unknown');
    assert.equal(model.batteryText({available:true,level:0}), '0%');
    assert.equal(model.batteryText({available:true,level:72,charging:true,stale:true}), '72% · Charging · Stale');
    assert.equal(model.batteryText({available:true,level:42,in_ear:true}, true), '42% · In ear · Stale');
});

test('battery presentation marks stale readings unavailable while retaining freshness in Diagnostics', () => {
    const status = model.parseStatus(sample({apple:{available:true, battery:{
        left:{available:true,level:93,freshness:'unknown'}, right:{available:false}, case:{available:true,level:0,stale:true},
    }}}));
    const popup = model.popupPresentation(status);
    assert.deepEqual(popup.battery.columns.map(column => column.text), ['93%', 'Unavailable', 'Unavailable']);
    assert.ok(popup.diagnostics.includes('Battery Left: 93% · Observation age unknown'));
    assert.ok(popup.diagnostics.includes('Battery Case: 0% · Stale'));
    assert.equal(popup.diagnostics.some(line => /age unknown|Stale/.test(line) && !line.startsWith('Battery ')), false);
});

test('Apple commands require explicit capabilities and fresh connected state', () => {
    const status = model.parseStatus(sample({apple:{available:true, capabilities:{noise_modes:['anc','adaptive'], conversation_awareness:true, one_bud_anc:true, ear_detection:true, adaptive_level:true}, state:{noise_mode:'adaptive'}}}));
    for (const verb of ['noise:anc','noise:adaptive','ca:on','onebud:off','ear:both','adaptive:25'])
        assert.deepEqual(model.commandArgs('apple', verb, status), ['apple',verb]);
    for (const verb of ['noise:off','forget','noise:cycle','adaptive:101','adaptive:2.5','ear:unknown','ca:yes'])
        assert.throws(() => model.commandArgs('apple', verb, status));
    for (const apple of [{available:true}, {...status.apple, stale:true}, {...status.apple, available:false}])
        assert.throws(() => model.commandArgs('apple','noise:anc',{...status,apple}));
    assert.throws(() => model.commandArgs('apple','noise:anc',{...status,connected:false}));
    assert.throws(() => model.commandArgs('apple','adaptive:20',{...status,apple:{...status.apple,state:{noise_mode:'anc'}}}));
});

test('command argv keeps microphone names literal and validates selections', () => {
    const status = model.parseStatus(sample({microphones:[{name:'node;$(literal)',description:'Input'}]}));
    assert.deepEqual(model.commandArgs('voxtype-pin','node;$(literal)',status), ['voxtype','pin','node;$(literal)']);
    assert.deepEqual(model.commandArgs('voxtype-default',null,status), ['voxtype','default']);
    for (const mode of ['music','meeting']) assert.deepEqual(model.commandArgs('mode',mode,status), ['mode',mode]);
    for (const action of ['connect','disconnect','status']) assert.deepEqual(model.commandArgs(action,null,status), [action]);
    for (const [action,value] of [['mode','bad'],['voxtype-pin','missing'],['voxtype-pin',''],['forget',null]])
        assert.throws(() => model.commandArgs(action,value,status));
});

test('compact popup presentation has native hierarchy, explicit state labels, and no invented battery', () => {
    const status = model.parseStatus(sample({
        device_name:'My AirPods', active_profile_description:'High Fidelity Playback (A2DP)',
        microphones:[{name:'bluez_input.1',description:'My AirPods microphone'}],
        voxtype:{mode:'pinned',source:'bluez_input.1',effective:{mode:'default',source:null},integration:'wrapper_running',pending_restart:true},
        apple:{available:true, capabilities:{noise_modes:['off','anc','transparency','adaptive'],conversation_awareness:true,one_bud_anc:true,ear_detection:true,adaptive_level:true},
            battery:{left:{available:true,level:82},right:{available:true,level:78},case:{available:false}},
            state:{noise_mode:'anc',conversation_awareness:true,one_bud_anc:false,ear_detection:'one',adaptive_level:null}}
    }));
    const popup = model.popupPresentation(status);
    assert.deepEqual(popup.sections.map(section => section.id), ['header','battery','audio-mode','noise-control','dictation','more-settings','footer']);
    assert.equal(popup.header.title, 'AirPods');
    assert.equal(popup.header.connection, 'Connected');
    assert.equal(popup.audioMode.description, 'High-quality playback');
    assert.deepEqual(popup.battery.columns.map(column => column.text), ['82%','78%','Unavailable']);
    assert.deepEqual(popup.audioMode.options.map(option => [option.label,option.selected,option.argv]), [
        ['Music',true,['mode','music']], ['Meeting',false,['mode','meeting']]]);
    assert.deepEqual(popup.noiseControl.options.map(option => [option.label, option.icon]), [
        ['Off', 'audio-volume-muted-symbolic'], ['Transparency', 'audio-speakers-symbolic'],
        ['Cancellation', 'audio-headphones-symbolic'], ['Adaptive', 'weather-overcast-symbolic'],
    ]);
    assert.equal(popup.noiseControl.options.find(option => option.id === 'anc').selected, true);
    assert.equal(popup.dictation.rowLabel, 'Dictation mic');
    assert.equal(popup.dictation.summary, 'AirPods microphone · Restart pending');
    assert.equal(popup.dictation.items.find(item => item.id === 'bluez_input.1').label, 'AirPods microphone');
    assert.deepEqual(popup.moreSettings.items.map(item => item.id), ['conversation-awareness','one-bud-anc','ear-detection','adaptive-level','diagnostics']);
    assert.equal(popup.footer.label, 'Disconnect');
});

test('disconnected presentation is generic and keeps only connection, routing, settings, and Connect', () => {
    const status = model.parseStatus(sample({device_name:'My AirPods', connected:false, apple:{available:false}}));
    const popup = model.popupPresentation(status);
    assert.equal(popup.header.title, 'AirPods');
    assert.equal(popup.header.connection, 'Disconnected');
    assert.equal(popup.disconnectedHint, 'Connect to see battery levels');
    assert.deepEqual(popup.sections.map(section => section.id), ['header', 'disconnected-hint', 'dictation', 'more-settings', 'footer']);
    assert.equal(popup.battery, null);
    assert.equal(popup.audioMode, null);
    assert.equal(popup.noiseControl, null);
    assert.ok(popup.dictation);
    assert.ok(popup.moreSettings);
    assert.deepEqual(popup.footer, {label:'Connect', action:'connect', enabled:true});
});

test('CLI failures and machine control errors surface safely, never count as status', () => {
    assert.equal(model.checkReply(0, '', ''), '');
    assert.equal(model.checkReply(0, sample(), ''), sample());
    assert.throws(() => model.checkReply(1, '', 'not\n running'), /not running/);
    assert.throws(() => model.checkReply(0, '{"error":"denied"}', ''), /denied/);
    assert.throws(() => model.checkReply(0, '{"ok":false}', ''), /failed/);
    assert.equal(model.safeText('a\nb\u0000c'), 'a b c');
    assert.ok(model.safeText('x'.repeat(1000)).length <= 160);
});

test('malformed nested companion fields are rejected rather than displayed as valid state', () => {
    for (const extra of [{desired_mode:'party'}, {active_profile:[]}, {active_profile_description:[]}, {device_name:{}}, {microphones:{}}, {microphones:[null]}, {microphones:[{name:'',description:'bad'}]}, {voxtype:{mode:'alsa'}}, {voxtype:{mode:'pinned',source:null}}, {apple:[]}])
        assert.throws(() => model.parseStatus(sample(extra)), /status/i);
    assert.equal(model.parseStatus(sample({desired_mode:null})).desired_mode, null);
    assert.doesNotThrow(() => model.parseStatus(sample({future_extra:{anything:true}})));
});

test('audio selection follows the observed PipeWire profile and configuration waits for a fresh connection', () => {
    const a2dp = model.parseStatus(sample({desired_mode:'meeting', active_profile:'a2dp-sink-sbc_xq'}));
    const music = model.popupPresentation(a2dp);
    assert.deepEqual(music.audioMode.options.map(option => [option.id, option.selected]), [['music',true], ['meeting',false]]);
    assert.equal(music.audioMode.description, 'High-quality playback');
    assert.equal(music.audioMode.pendingHint, 'Mode change pending');

    const hfp = model.popupPresentation(model.parseStatus(sample({desired_mode:'music', active_profile:'headset-head-unit-msbc'})));
    assert.deepEqual(hfp.audioMode.options.map(option => option.selected), [false,true]);
    assert.equal(hfp.audioMode.description, 'Headset microphone · reduced playback quality');
    assert.equal(hfp.audioMode.pendingHint, 'Mode change pending');

    const unknown = model.popupPresentation(model.parseStatus(sample({active_profile:'vendor-profile'})));
    assert.deepEqual(unknown.audioMode.options.map(option => option.selected), [false,false]);

    const disconnected = model.popupPresentation(model.parseStatus(sample({connected:false, apple:{available:false}})));
    assert.equal(disconnected.audioMode, null);
    assert.equal(disconnected.dictation.items.every(item => item.enabled === false), true);
    assert.equal(disconnected.footer.label, 'Connect');
    assert.equal(disconnected.footer.enabled, true);
    assert.equal(model.canAct('connect', null, disconnected.status, {}), true);
    assert.equal(model.canAct('mode', 'music', disconnected.status, {}), false);
    assert.equal(model.canAct('connect', null, disconnected.status, {stale:true}), false);
});
