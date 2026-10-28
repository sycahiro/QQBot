import test from 'node:test';
import assert from 'node:assert/strict';
import {
    addNotice,
    dismissNotice,
    getNotices,
    subscribeNotices,
} from '../src/components/notice-store.ts';
import { CheckDeadlineError, waitForCheck } from '../src/settings/check-deadline.ts';

test('notifications put newest first, preserve older messages, bound the stack and close once', () => {
    let changes = 0;
    const closed = [];
    const unsubscribe = subscribeNotices(() => changes++);
    const ids = [];
    for (let i = 0; i < 5; i++)
        ids.push(
            addNotice({ message: `notice-${i}`, error: false, onClose: () => closed.push(i) }),
        );
    assert.deepEqual(
        getNotices().map((n) => n.message),
        ['notice-4', 'notice-3', 'notice-2', 'notice-1'],
    );
    assert.deepEqual(closed, [0]);
    dismissNotice(ids[2]);
    dismissNotice(ids[2]);
    assert.deepEqual(closed, [0, 2]);
    assert.deepEqual(
        getNotices().map((n) => n.message),
        ['notice-4', 'notice-3', 'notice-1'],
    );
    for (const entry of getNotices()) dismissNotice(entry.id);
    assert.ok(changes >= 9);
    unsubscribe();
});

test('lost model-check acknowledgement expires without retrying or accepting a late response', async () => {
    let complete;
    const pending = new Promise((resolve) => {
        complete = resolve;
    });
    await assert.rejects(waitForCheck(pending, 5), CheckDeadlineError);
    complete('late');
    assert.equal(await waitForCheck(Promise.resolve('ready'), 100), 'ready');
    await assert.rejects(waitForCheck(Promise.reject(new Error('failed')), 100), /failed/);
});
