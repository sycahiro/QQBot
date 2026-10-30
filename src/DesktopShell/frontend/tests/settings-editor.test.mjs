import test from 'node:test';
import assert from 'node:assert/strict';
import { SettingsEditor } from '../src/agent/settings-editor.ts';

const ACCOUNT = '12345678';
const config = () => ({
    api: {
        protocol: 'chat',
        sendTemperature: true,
        maxOutputTokens: 4096,
        chatTokenLimitField: 'max_tokens',
        baseUrl: 'https://model.test/v1',
        model: 'test',
        apiKeyConfigured: true,
        temperature: 0.8,
        maxRounds: 12,
        timeoutMs: 90000,
        vision: false,
        visionModel: '',
        sendImages: false,
        video: false,
        videoMode: 'frames',
        videoModel: '',
        videoFrames: 6,
    },
    persona: { roleText: 'original', customRules: '' },
    defaultPersona: { roleText: 'default', customRules: 'default rules' },
    allow: { groups: [], private: [] },
    deny: { groups: [], private: [] },
    blockedUsers: [],
    groupTrigger: 'at',
    groupKeywords: [],
    groupRandomPercent: 10,
    contextLimit: 40,
    profiles: [],
    activeProfileId: '',
    webSearch: {
        enabled: false,
        maxResults: 6,
        browse: true,
        mode: 'local',
        fallback: true,
        searchProfileId: '',
    },
    sticker: { enabled: false, collectEnabled: false, allowPoke: false },
});
const change = (e, patch) => e.change({ ...e.getSnapshot().draft, ...patch });
const role = (e, text) =>
    change(e, {
        config: { ...e.getSnapshot().draft.config, persona: { roleText: text, customRules: '' } },
    });
function editor(
    save,
    profile = async () => {
        throw Error('unexpected profile write');
    },
) {
    return new SettingsEditor(ACCOUNT, config(), save, profile);
}

test('saving the default persona writes persona text together with the admin QQ', async () => {
    const calls = [];
    const e = editor(async (patch) => {
        calls.push(patch);
        return { ok: true, account: ACCOUNT, config: { ...config(), ...patch } };
    });
    const draft = e.getSnapshot().draft;
    change(e, {
        config: {
            ...draft.config,
            defaultPersona: { roleText: 'new default', customRules: 'rule' },
            ownerQQ: '10086',
        },
    });
    assert.ok(e.dirty('defaultPersona'));
    await e.save('defaultPersona');
    // 管理员 QQ 必须随同一张卡片保存；漏发会导致输入框被回读清空。
    assert.deepEqual(calls, [
        {
            defaultPersona: { roleText: 'new default', customRules: 'rule' },
            ownerQQ: '10086',
        },
    ]);
    assert.ok(!e.dirty('defaultPersona'));
});
test('editing never writes until the corresponding save button is invoked', async () => {
    const calls = [];
    const e = editor(async (patch) => {
        calls.push(patch);
        return { ok: true, account: ACCOUNT, config: { ...config(), ...patch } };
    });
    role(e, 'new');
    await new Promise((r) => setTimeout(r, 800));
    assert.equal(calls.length, 0);
    assert.ok(e.dirty('persona'));
    await e.save('persona');
    assert.deepEqual(calls, [{ persona: { roleText: 'new', customRules: '' } }]);
    assert.ok(!e.dirty('persona'));
});
test('saving one card excludes model, key, and other unsaved drafts', async () => {
    const calls = [];
    const e = editor(async (patch) => {
        calls.push(patch);
        return { ok: true, account: ACCOUNT, config: { ...config(), ...patch } };
    });
    role(e, 'new');
    change(e, {
        key: 'memory-only',
        lists: { ...e.getSnapshot().draft.lists, groups: '99887766' },
    });
    await e.save('persona');
    assert.deepEqual(Object.keys(calls[0]), ['persona']);
    assert.equal(e.getSnapshot().draft.lists.groups, '99887766');
    assert.equal(e.getSnapshot().draft.key, 'memory-only');
    assert.ok(e.dirty('model') && e.dirty('scope'));
});
test('late saves preserve edits made in the same card while saving', async () => {
    let finish;
    const e = editor(
        (patch) =>
            new Promise((r) => {
                finish = () => r({ ok: true, account: ACCOUNT, config: { ...config(), ...patch } });
            }),
    );
    role(e, 'first');
    const saving = e.save('persona');
    role(e, 'latest');
    finish();
    await saving;
    assert.equal(e.getSnapshot().draft.config.persona.roleText, 'latest');
    assert.ok(e.dirty('persona'));
});
test('failed saves keep drafts without retrying or leaking exception values', async () => {
    let calls = 0;
    const e = editor(async () => {
        calls++;
        throw Error('secret-key');
    });
    role(e, 'draft');
    await e.save('persona');
    assert.equal(calls, 1);
    assert.ok(e.dirty('persona'));
    assert.ok(!e.getSnapshot().errors.persona.includes('secret-key'));
});
test('scope and advanced save only their own fields and normalize number lists', async () => {
    const calls = [];
    const e = editor(async (patch) => {
        calls.push(patch);
        return { ok: true, account: ACCOUNT, config: { ...config(), ...patch } };
    });
    change(e, {
        lists: {
            groups: '99887766,99887766',
            private: '11223344',
            denyGroups: '88776655',
            denyPrivate: '',
            blocked: '22334455',
        },
        keywords: 'test\nTEST',
    });
    await e.save('scope');
    assert.deepEqual(calls[0].allow.groups, ['99887766']);
    assert.ok(!('api' in calls[0]) && !('deny' in calls[0]));
    await e.save('advanced');
    assert.deepEqual(Object.keys(calls[1]).sort(), ['blockedUsers', 'deny']);
});
test('model profile saving keeps credentials write-only and clears only acknowledged keys', async () => {
    let submitted;
    const e = editor(
        async () => {
            throw Error();
        },
        async (op, data) => {
            submitted = data;
            const c = config();
            c.api.apiKeyConfigured = true;
            c.activeProfileId = 'p1';
            c.profiles = [{ id: 'p1', name: data.name, api: c.api }];
            return { ok: true, account: ACCOUNT, config: c };
        },
    );
    change(e, { key: 'new-key' });
    await e.save('model');
    assert.equal(submitted.api.apiKey, 'new-key');
    assert.ok(!('apiKeyConfigured' in submitted.api));
    assert.equal(e.getSnapshot().draft.key, '');
    assert.equal(e.getSnapshot().draft.profileId, 'p1');
});
test('new profiles start with empty endpoint/key and never copy another profile key', () => {
    const e = editor(async () => {
        throw Error();
    });
    change(e, { key: 'unsaved-key' });
    e.pick(null);
    assert.equal(e.getSnapshot().draft.config.api.baseUrl, '');
    assert.equal(e.getSnapshot().draft.key, '');
    assert.equal(e.getSnapshot().draft.config.api.apiKeyConfigured, false);
});

test('marking and undoing key removal never writes; only model save clears the selected key', async () => {
    const calls = [];
    const e = editor(
        async () => {
            throw Error('unexpected settings write');
        },
        async (op, data) => {
            calls.push(data);
            const c = config();
            c.api.apiKeyConfigured = false;
            c.activeProfileId = 'p1';
            c.profiles = [{ id: 'p1', name: data.name, api: c.api }];
            return { ok: true, account: ACCOUNT, config: c };
        },
    );
    change(e, { key: 'unsaved-new-key', clearKey: true });
    assert.equal(calls.length, 0);
    change(e, { clearKey: false });
    assert.equal(e.getSnapshot().draft.key, 'unsaved-new-key');
    assert.equal(calls.length, 0);
    change(e, { clearKey: true });
    await e.save('model');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].api.apiKey, '');
    assert.equal(e.getSnapshot().draft.key, '');
    assert.equal(e.getSnapshot().draft.clearKey, false);
});
test('wrong-account acknowledgements cannot replace drafts', async () => {
    const e = editor(async () => ({ ok: true, account: '87654321', config: config() }));
    role(e, 'keep');
    await e.save('persona');
    assert.equal(e.getSnapshot().draft.config.persona.roleText, 'keep');
    assert.match(e.getSnapshot().errors.persona, /账号/);
});
test('disposing cancels unsaved credentials without initiating a save', async () => {
    let calls = 0;
    const e = editor(async () => {
        calls++;
        throw Error();
    });
    change(e, { key: 'unsaved' });
    e.dispose();
    await e.save('model');
    assert.equal(calls, 0);
    assert.equal(e.getSnapshot().draft.key, '');
});

test('search and sticker cards save independently without model key or persona drafts', async () => {
    const calls = [];
    const e = editor(async (patch) => {
        calls.push(patch);
        const c = config();
        return { ok: true, account: ACCOUNT, config: { ...c, ...patch } };
    });
    role(e, 'draft');
    change(e, {
        key: 'model-secret',
        config: {
            ...e.getSnapshot().draft.config,
            webSearch: { ...config().webSearch, enabled: true },
            sticker: { enabled: true, collectEnabled: false },
        },
    });
    await e.save('search');
    assert.deepEqual(Object.keys(calls[0]), ['webSearch']);
    assert.deepEqual(calls[0].webSearch, { ...config().webSearch, enabled: true });
    assert.equal(e.getSnapshot().draft.key, 'model-secret');
    assert.ok(e.dirty('persona') && e.dirty('sticker'));
    await e.save('sticker');
    assert.deepEqual(Object.keys(calls[1]), ['sticker']);
    assert.ok(e.dirty('persona'));
    e.dispose();
    assert.equal(e.getSnapshot().draft.key, '');
});

test('model save leaves media to the separately saved page', async () => {
    let submitted;
    const e = editor(
        async () => {
            throw Error();
        },
        async (op, data) => {
            submitted = data;
            return { ok: true, account: ACCOUNT, config: config() };
        },
    );
    await e.save('model');
    assert.ok(
        !('vision' in submitted.api) &&
            !('video' in submitted.api) &&
            !('visionModel' in submitted.api),
    );
    assert.equal(submitted.api.model, 'test');
});

test('protocol and protocol parameters are saved with the model profile', async () => {
    let submitted;
    const e = editor(
        async () => {
            throw Error();
        },
        async (op, data) => {
            submitted = data;
            const c = config();
            return { ok: true, account: ACCOUNT, config: { ...c, api: { ...c.api, ...data.api } } };
        },
    );
    change(e, {
        config: {
            ...config(),
            api: {
                ...config().api,
                protocol: 'anthropic',
                sendTemperature: false,
                maxOutputTokens: 8192,
                chatTokenLimitField: 'max_completion_tokens',
            },
        },
    });
    await e.save('model');
    assert.equal(submitted.api.protocol, 'anthropic');
    assert.equal(submitted.api.sendTemperature, false);
    assert.equal(submitted.api.maxOutputTokens, 8192);
    assert.equal(submitted.api.chatTokenLimitField, 'max_completion_tokens');
    assert.ok(!('vision' in submitted.api));
});

test('disposed editor ignores a late reconcile without restoring a draft', () => {
    const e = editor(async () => {
        throw Error('unexpected write');
    });
    e.dispose();
    const before = e.getSnapshot();
    e.reconcile({ ...config(), api: { ...config().api, model: 'late' } });
    assert.equal(e.getSnapshot(), before);
});

test('chat limit field participates in dirty checking and preserves newer edits while saving', async () => {
    let release;
    let submitted;
    const e = editor(
        async () => {
            throw Error('unexpected write');
        },
        async (_, data) => {
            submitted = data;
            return await new Promise((resolve) => {
                release = resolve;
            });
        },
    );
    change(e, {
        config: {
            ...config(),
            api: { ...config().api, chatTokenLimitField: 'max_completion_tokens' },
        },
    });
    assert.equal(e.dirty('model'), true);
    const pending = e.save('model');
    change(e, {
        config: { ...config(), api: { ...config().api, chatTokenLimitField: 'max_tokens' } },
    });
    release({
        ok: true,
        account: ACCOUNT,
        config: { ...config(), api: { ...config().api, ...submitted.api } },
    });
    await pending;
    assert.equal(submitted.api.chatTokenLimitField, 'max_completion_tokens');
    assert.equal(e.getSnapshot().draft.config.api.chatTokenLimitField, 'max_tokens');
    assert.equal(e.dirty('model'), true);
});

test('switching profiles keeps separate unsaved models and keys without writing or activating', async () => {
    const c = config();
    c.activeProfileId = 'p1';
    c.profiles = [
        { id: 'p1', name: 'One', api: { ...c.api } },
        { id: 'p2', name: 'Two', api: { ...c.api, model: 'two' } },
    ];
    let writes = 0;
    const e = new SettingsEditor(
        ACCOUNT,
        c,
        async () => {
            writes++;
            throw Error();
        },
        async () => {
            writes++;
            throw Error();
        },
    );
    change(e, { key: 'draft-key-one', config: { ...c, api: { ...c.api, model: 'draft-one' } } });
    e.pick('p2');
    assert.equal(e.getSnapshot().draft.key, '');
    assert.equal(e.getSnapshot().draft.config.api.model, 'two');
    change(e, { key: 'draft-key-two' });
    e.pick('p1');
    assert.equal(e.getSnapshot().draft.key, 'draft-key-one');
    assert.equal(e.getSnapshot().draft.config.api.model, 'draft-one');
    e.pick('p2');
    assert.equal(e.getSnapshot().draft.key, 'draft-key-two');
    e.pick(null);
    change(e, { profileName: 'Unfinished', key: 'new-draft-key' });
    e.pick('p1');
    e.pick(null);
    assert.equal(e.getSnapshot().draft.key, 'new-draft-key');
    assert.equal(e.getSnapshot().draft.profileName, 'Unfinished');
    assert.equal(e.getSnapshot().config.activeProfileId, 'p1');
    assert.equal(writes, 0);
    e.dispose();
    e.pick('p1');
    assert.equal(e.getSnapshot().draft.key, '');
});

test('profile draft cache never restores a key that has already been saved', async () => {
    const c = config();
    c.activeProfileId = 'p1';
    c.profiles = [
        { id: 'p1', name: 'One', api: { ...c.api } },
        { id: 'p2', name: 'Two', api: { ...c.api, model: 'two' } },
    ];
    const e = new SettingsEditor(
        ACCOUNT,
        c,
        async () => {
            throw Error();
        },
        async (op, data) => ({
            ok: true,
            account: ACCOUNT,
            config: { ...c, api: { ...c.api, model: data.api.model } },
        }),
    );
    change(e, { key: 'one-key', config: { ...c, api: { ...c.api, model: 'updated' } } });
    e.pick('p2');
    e.pick('p1');
    await e.save('model');
    e.pick('p2');
    e.pick('p1');
    assert.equal(e.getSnapshot().draft.key, '');
    assert.equal(e.getSnapshot().draft.config.api.model, 'updated');
});

test('sticker switches save only the changed field and preserve text and key drafts', async () => {
    let submitted;
    const e = editor(async (patch) => {
        submitted = patch;
        const c = config();
        return {
            ok: true,
            account: ACCOUNT,
            config: { ...c, sticker: { ...c.sticker, ...patch.sticker } },
        };
    });
    role(e, 'unfinished persona');
    change(e, { key: 'unsaved-model-key' });
    await e.toggleSticker('enabled', true);
    assert.deepEqual(submitted, { sticker: { enabled: true } });
    assert.equal(e.getSnapshot().draft.config.sticker.enabled, true);
    assert.equal(e.getSnapshot().draft.key, 'unsaved-model-key');
    assert.equal(e.getSnapshot().draft.config.persona.roleText, 'unfinished persona');
    assert.ok(e.dirty('persona') && e.dirty('model'));
});

test('failed switch save rolls back and overlapping toggle requests never race', async () => {
    let finish,
        calls = 0;
    const e = editor(() => {
        calls++;
        return new Promise((resolve) => {
            finish = () => resolve({ ok: false, error: { code: 'FAIL', message: 'write failed' } });
        });
    });
    const pending = e.toggleSticker('enabled', true);
    assert.equal(e.getSnapshot().draft.config.sticker.enabled, true);
    await e.toggleSticker('collectEnabled', true);
    assert.equal(calls, 1);
    role(e, 'newer persona');
    finish();
    await pending;
    assert.equal(e.getSnapshot().draft.config.sticker.enabled, false);
    assert.equal(e.getSnapshot().draft.config.persona.roleText, 'newer persona');
    assert.equal(e.getSnapshot().saving, null);
    assert.ok(e.getSnapshot().errors.sticker);
});
