import test from 'node:test';
import assert from 'node:assert/strict';
import { lockModalBackground } from '../src/components/modal-background.ts';

for (const firstToClose of [0, 1])
    test(`stacked confirmations keep the workspace inert until both close (order ${firstToClose})`, () => {
        const root = { inert: false };
        const release = [lockModalBackground(root), lockModalBackground(root)];
        release[firstToClose]();
        assert.equal(root.inert, true);
        release[firstToClose]();
        assert.equal(root.inert, true, 'cleanup is idempotent');
        release[1 - firstToClose]();
        assert.equal(root.inert, false);
    });
test('modal cleanup preserves a preexisting inert background', () => {
    const root = { inert: true };
    const release = lockModalBackground(root);
    release();
    assert.equal(root.inert, true);
    lockModalBackground(null)();
});
