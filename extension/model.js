// SPDX-License-Identifier: GPL-3.0-or-later
export function parseStatus(text) {
    let value;
    try { value = JSON.parse(text); } catch { throw new Error('Invalid companion status JSON'); }
    if (!value || Array.isArray(value) || value.schema_version !== 1)
        throw new Error('Unsupported companion status schema (requires 1)');
    if (typeof value.connected !== 'boolean')
        throw new Error('Invalid connected field in status');
    for (const key of ['device_name', 'active_profile', 'error'])
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
