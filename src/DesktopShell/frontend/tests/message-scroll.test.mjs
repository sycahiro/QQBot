import test from 'node:test';
import assert from 'node:assert/strict';
import { MessageScroll } from '../src/agent/message-scroll.ts';

const view = (top, total, rows = []) => ({ top, height: 200, total, rows });

test('opening an archive waits for data then positions at the newest message', () => {
    const scroll = new MessageScroll();
    assert.equal(scroll.position(view(0, 200), false), null);
    assert.equal(scroll.position(view(0, 1200), true), 1200);
    assert.equal(scroll.position(view(1000, 1400), true), 1400);
});
test('reading older messages stays on the same visible message as animated prepends grow', () => {
    const scroll = new MessageScroll();
    scroll.position(view(0, 1000), true);
    scroll.scrolled(
        view(300, 1000, [
            { id: '4', top: -20, bottom: 80 },
            { id: '5', top: 80, bottom: 180 },
        ]),
    );
    assert.equal(
        scroll.position(
            view(300, 1020, [
                { id: '4', top: 0, bottom: 100 },
                { id: '5', top: 100, bottom: 200 },
            ]),
            true,
        ),
        320,
    );
    // The measured position after scrolling is the same original message/offset.
    scroll.remember(
        view(320, 1020, [
            { id: '4', top: -20, bottom: 80 },
            { id: '5', top: 80, bottom: 180 },
        ]),
    );
    assert.equal(
        scroll.position(
            view(320, 1100, [
                { id: '4', top: 60, bottom: 160 },
                { id: '5', top: 160, bottom: 260 },
            ]),
            true,
        ),
        400,
    );
});
test('new arrivals and polling do not pull a reader away; scrolling to the end resumes following', () => {
    const scroll = new MessageScroll();
    scroll.position(view(0, 1000), true);
    scroll.scrolled(view(300, 1000, [{ id: '4', top: -20, bottom: 80 }]));
    assert.equal(scroll.position(view(300, 1200, [{ id: '4', top: -20, bottom: 80 }]), true), 300);
    scroll.scrolled(view(1000, 1200));
    assert.equal(scroll.position(view(1000, 1300), true), 1300);
});
test('search results start at the first result without following new matches', () => {
    const scroll = new MessageScroll(false);
    assert.equal(scroll.position(view(0, 1200), true), 0);
    scroll.scrolled(view(1000, 1200));
    assert.equal(scroll.position(view(1000, 1400), true), null);
});
test('pagination pauses following and return to latest explicitly restores it', () => {
    const scroll = new MessageScroll();
    scroll.position(view(0, 1000), true);
    scroll.pause(view(800, 1000, [{ id: '9', top: 0, bottom: 100 }]));
    assert.equal(scroll.position(view(800, 1100, [{ id: '9', top: 100, bottom: 200 }]), true), 900);
    scroll.latest();
    assert.equal(scroll.position(view(900, 1600), true), 1600);
});
