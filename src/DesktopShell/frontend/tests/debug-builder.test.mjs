import test from 'node:test';
import assert from 'node:assert/strict';
import { buildMessage, newSegment } from '../src/debug/builder.ts';

test('rich builder emits ordered OneBot segments and only opaque attachment handles', () => {
    const text = { ...newSegment(), value: 'hello' },
        image = {
            ...newSegment('image'),
            attachment: { token: 'a'.repeat(32), name: 'private.png', kind: 'image', bytes: 50 },
        },
        reply = { ...newSegment('reply'), value: '-12' };
    assert.deepEqual(buildMessage([reply, text, image], false), [
        { type: 'reply', data: { id: '-12' } },
        { type: 'text', data: { text: 'hello' } },
        { type: 'image', data: { file: 'a'.repeat(32) } },
    ]);
    assert.ok(!JSON.stringify(buildMessage([image], false)).includes('private.png'));
    assert.notEqual(text.id, image.id);
});
test('forward nodes contain only content and cannot claim another sender identity', () => {
    const value = buildMessage(
        [
            { ...newSegment(), value: 'one' },
            { ...newSegment('face'), value: '14' },
        ],
        true,
    );
    assert.deepEqual(value, [
        { type: 'node', data: { content: [{ type: 'text', data: { text: 'one' } }] } },
        { type: 'node', data: { content: [{ type: 'face', data: { id: '14' } }] } },
    ]);
    assert.ok(value.every((v) => Object.keys(v.data).join(',') === 'content'));
});
