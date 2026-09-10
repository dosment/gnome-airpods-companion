// SPDX-License-Identifier: GPL-3.0-or-later
export function parseStatus(text) {
    let value;
    try { value = JSON.parse(text); } catch { throw new Error('Invalid companion status JSON'); }
    if (!value || Array.isArray(value) || value.schema_version !== 1)
        throw new Error('Unsupported companion status schema (requires 1)');
    if (typeof value.connected !== 'boolean')
        throw new Error('Invalid connected field in status');
    for (const key of ['device_name', 'active_profile', 'active_profile_description', 'error'])
        if (value[key] != null && typeof value[key] !== 'string')
            throw new Error(`Invalid ${key} in status`);
    if (value.desired_mode != null && !['music', 'meeting'].includes(value.desired_mode))
        throw new Error('Invalid desired_mode in status');
    if (value.microphones !== undefined && (!Array.isArray(value.microphones) || value.microphones.some(m =>
        !m || typeof m.name !== 'string' || !m.name || m.name.includes('\0') ||
        (m.description !== undefined && typeof m.description !== 'string'))))
        throw new Error('Invalid microphones in status');
    if (value.voxtype !== undefined && (!value.voxtype || !['default', 'pinned'].includes(value.voxtype.mode) ||
        (value.voxtype.mode === 'pinned' && (typeof value.voxtype.source !== 'string' || !value.voxtype.source))))
        throw new Error('Invalid voxtype in status');
    if (value.apple !== undefined && (!value.apple || typeof value.apple !== 'object' || Array.isArray(value.apple)))
        throw new Error('Invalid apple in status');
    return value;
}

export function batteryText(value, stale = false) {
    if (!value || value.available !== true || !Number.isInteger(value.level) || value.level < 0 || value.level > 100)
        return 'Unavailable';
    return [`${value.level}%`, value.charging === true ? 'Charging' : '',
        value.in_ear === true ? 'In ear' : '', stale || value.stale === true ? 'Stale' : '',
        value.freshness === 'unknown' ? 'Observation age unknown' : ''].filter(Boolean).join(' · ');
}

export function commandArgs(action, value, status) {
    if (['status', 'connect', 'disconnect'].includes(action)) return [action];
    if (action === 'mode' && ['music', 'meeting'].includes(value)) return ['mode', value];
    if (action === 'voxtype-default') return ['voxtype', 'default'];
    if (action === 'voxtype-pin' && typeof value === 'string' && value.length > 0 && !value.includes('\0') &&
        Array.isArray(status?.microphones) && status.microphones.some(m => m?.name === value))
        return ['voxtype', 'pin', value];
    if (action === 'apple') {
        const apple = status?.apple;
        const cap = apple?.capabilities ?? {};
        let allowed = false;
        if (status?.connected === true && apple?.available === true && apple.stale !== true) {
            if (/^noise:(off|anc|transparency|adaptive)$/.test(value))
                allowed = Array.isArray(cap.noise_modes) && cap.noise_modes.includes(value.split(':')[1]);
            else if (/^ca:(on|off)$/.test(value)) allowed = cap.conversation_awareness === true;
            else if (/^onebud:(on|off)$/.test(value)) allowed = cap.one_bud_anc === true;
            else if (/^ear:(one|both|off)$/.test(value)) allowed = cap.ear_detection === true;
            else if (/^adaptive:(0|[1-9][0-9]?|100)$/.test(value))
                allowed = cap.adaptive_level === true && apple.state?.noise_mode === 'adaptive';
        }
        if (allowed) return ['apple', value];
    }
    throw new Error('Unsupported or unavailable control');
}

export function canAct(action, value, status, {stale = false, changing = false, pending = false} = {}) {
    if (stale || changing || pending || !status) return false;
    if (action === 'connect') return status.connected === false;
    if (action !== 'status' && status.connected !== true) return false;
    try { commandArgs(action, value, status); return true; } catch { return false; }
}

function observedAudioMode(profile) {
    const value = String(profile || '').toLowerCase();
    if (value.includes('a2dp')) return 'music';
    if (value.includes('headset-head-unit') || value.includes('hfp') || value.includes('hsp')) return 'meeting';
    return null;
}

function compactBatteryText(value, stale = false) {
    if (!value || value.available !== true || !Number.isInteger(value.level) || value.level < 0 || value.level > 100)
        return 'Unavailable';
    if (stale || value.stale === true) return `${value.level}% · stale`;
    if (value.freshness === 'unknown') return `${value.level}% · age unknown`;
    return `${value.level}%`;
}

export function popupPresentation(status, {stale = false, changing = false, error = ''} = {}) {
    const enabled = (action, value = null) => canAct(action, value, status, {stale, changing});
    const apple = status?.apple ?? {};
    const cap = apple.capabilities ?? {};
    const state = apple.state ?? {};
    const noiseNames = {off: 'Off', anc: 'Noise Cancellation', transparency: 'Transparency', adaptive: 'Adaptive'};
    const noiseOrder = ['off', 'transparency', 'anc', 'adaptive'];
    const noiseModes = noiseOrder.filter(mode => Array.isArray(cap.noise_modes) && cap.noise_modes.includes(mode));
    const batteryParts = apple.is_headset === true ? [['headset', 'Headphones']] : [['left', 'Left'], ['right', 'Right'], ['case', 'Case']];
    const battery = {columns: batteryParts.map(([id, label]) => ({id, label,
        text: compactBatteryText(apple.battery?.[id], stale || !status?.connected || apple.available !== true || apple.stale === true)}))};
    const desired = status?.desired_mode;
    const observed = observedAudioMode(status?.active_profile);
    const observedLabel = observed ? (observed === 'music' ? 'Music' : 'Meeting') : 'Unavailable';
    const audioMode = {description: `Observed: ${observedLabel}`,
        pendingHint: desired && desired !== observed ? `Requested ${desired === 'music' ? 'Music' : 'Meeting'} · observed ${observedLabel}` : null, options: [
        {id: 'music', label: 'Music', icon: 'audio-x-generic-symbolic', selected: observed === 'music', enabled: enabled('mode', 'music'), argv: ['mode', 'music']},
        {id: 'meeting', label: 'Meeting', icon: 'microphone-sensitivity-high-symbolic', selected: observed === 'meeting', enabled: enabled('mode', 'meeting'), argv: ['mode', 'meeting']},
    ]};
    const noiseControl = noiseModes.length ? {options: noiseModes.map(id => ({id, label: noiseNames[id],
        selected: state.noise_mode === id, enabled: enabled('apple', `noise:${id}`), argv: ['apple', `noise:${id}`]}))} : null;
    const vox = status?.voxtype ?? {};
    const pinnedSource = Array.isArray(status?.microphones) ? status.microphones.find(source => source?.name === vox.source) : null;
    const micName = vox.mode === 'pinned' ? (pinnedSource?.description || vox.source || 'Unavailable') : 'System default';
    const dictation = {summary: `${micName}${vox.pending_restart === true ? ' · Restart pending' : ''}`,
        enabled: status?.connected === true && !stale && !changing, items: [{id: 'default', label: 'Follow Ubuntu default input', selected: vox.mode !== 'pinned', enabled: enabled('voxtype-default'), argv: ['voxtype', 'default']},
            ...(Array.isArray(status?.microphones) ? status.microphones.map(source => ({id: source.name, label: source.description || source.name,
                selected: vox.mode === 'pinned' && vox.source === source.name, enabled: enabled('voxtype-pin', source.name), argv: ['voxtype', 'pin', source.name]})) : [])]};
    const moreItems = [];
    if (cap.conversation_awareness === true) moreItems.push({id: 'conversation-awareness', label: `Conversation Awareness · Reported: ${state.conversation_awareness === true ? 'On' : state.conversation_awareness === false ? 'Off' : 'Unknown'}`, action: 'ca'});
    if (cap.one_bud_anc === true) moreItems.push({id: 'one-bud-anc', label: `One-Bud ANC · Reported: ${state.one_bud_anc === true ? 'On' : state.one_bud_anc === false ? 'Off' : 'Unknown'}`, action: 'onebud'});
    if (cap.ear_detection === true) moreItems.push({id: 'ear-detection', label: `Ear detection · Local policy: ${{one: 'Pause when one is out', both: 'Pause when both are out', off: 'Never pause'}[state.ear_detection] || 'Unknown'}`, action: 'ear'});
    if (cap.adaptive_level === true) moreItems.push({id: 'adaptive-level', label: `Adaptive noise level · Reported: ${Number.isInteger(state.adaptive_level) ? state.adaptive_level : 'Unknown'}${state.noise_mode === 'adaptive' ? '' : ' · Select Adaptive to change'}`, action: 'adaptive'});
    moreItems.push({id: 'diagnostics', label: 'Diagnostics', action: 'diagnostics'});
    const diagnostics = [
        changing ? 'Applying… Waiting for status readback' : null,
        error ? `Error: ${safeText(error)}` : null,
        status?.error ? `Backend: ${safeText(status.error)}` : null,
        apple.error ? `Apple: ${safeText(apple.error)}` : null,
        stale ? 'Status unavailable · Retained observations are stale' : null,
        status?.active_profile ? `Observed PipeWire profile: ${safeText(status.active_profile)}` : null,
        status?.active_profile_description ? `Profile detail: ${safeText(status.active_profile_description)}` : null,
        ...battery.columns.map(column => {
            const value = apple.battery?.[column.id];
            if (!value || value.available !== true) return `Battery ${column.label}: Unavailable`;
            return `Battery ${column.label}: ${value.level}%${value.charging === true ? ' · Charging' : ''}${value.in_ear === true ? ' · In ear' : ''}${value.stale === true ? ' · Stale' : ''}${value.freshness === 'unknown' ? ' · Observation age unknown' : ''}`;
        }),
        'Refresh status',
    ].filter(Boolean);
    const footer = {label: status?.connected ? 'Disconnect' : 'Connect', action: status?.connected ? 'disconnect' : 'connect', enabled: enabled(status?.connected ? 'disconnect' : 'connect')};
    const notice = changing ? 'Applying…' : error ? `Error: ${safeText(error)}` : null;
    return {status, notice, header: {title: safeText(status?.device_name || 'AirPods Companion'), connection: stale ? 'Status unavailable · Last reading is stale' : status ? (status.connected ? 'Connected' : 'Disconnected') : 'Reading companion status…'}, battery, audioMode, noiseControl, dictation, moreSettings: {items: moreItems}, diagnostics, footer,
        sections: ['header', 'battery', 'audio-mode', 'noise-control', 'dictation', 'more-settings', 'footer'].map(id => ({id}))};
}

export function safeText(value) {
    return String(value ?? '').replace(/[\s\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]+/g, ' ').trim().slice(0, 160);
}
export function checkReply(exitCode, stdout, stderr, isStatus = false) {
    if (exitCode !== 0) throw new Error(safeText(stderr) || `Companion exited with code ${exitCode}`);
    let value;
    try { value = JSON.parse(stdout); } catch { return stdout; }
    if (!isStatus && (value?.error || value?.ok === false))
        throw new Error(safeText(value.error) || 'Companion command failed');
    return stdout;
}
