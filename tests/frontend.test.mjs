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
    for (const extra of [{desired_mode:'party'}, {active_profile:[]}, {device_name:{}}, {microphones:{}}, {microphones:[null]}, {microphones:[{name:'',description:'bad'}]}, {voxtype:{mode:'alsa'}}, {voxtype:{mode:'pinned',source:null}}, {apple:[]}])
        assert.throws(() => model.parseStatus(sample(extra)), /status/i);
    assert.equal(model.parseStatus(sample({desired_mode:null})).desired_mode, null);
    assert.doesNotThrow(() => model.parseStatus(sample({future_extra:{anything:true}})));
});
