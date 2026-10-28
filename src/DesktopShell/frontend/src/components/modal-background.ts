const locks = new WeakMap<HTMLElement, { count: number; previous: boolean }>();

/** Nested dialogs share one background lock and restore its original state. */
export function lockModalBackground(root: HTMLElement | null): () => void {
    if (!root) return () => {};
    const state = locks.get(root) ?? { count: 0, previous: root.inert };
    state.count++;
    locks.set(root, state);
    root.inert = true;
    let released = false;
    return () => {
        if (released) return;
        released = true;
        if (--state.count === 0) {
            root.inert = state.previous;
            locks.delete(root);
        }
    };
}
