import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { scrollToY } from '../motion';

/** Keep the old scroll extent until the new panel has entered and scrolled home. */
export function useTabNavigation<T extends string>(initial: T) {
    const [tab, change] = useState(initial),
        [minHeight, setMinHeight] = useState<number>();
    const panel = useRef<HTMLDivElement>(null),
        cancelScroll = useRef<(() => void) | null>(null);
    const reduced = useReducedMotion();
    useEffect(() => () => cancelScroll.current?.(), []);
    const setTab = (next: T) => {
        if (next === tab) return;
        cancelScroll.current?.();
        setMinHeight(panel.current?.offsetHeight);
        change(next);
    };
    const onExitComplete = () => {
        const element = document.getElementById('main-content');
        if (element)
            cancelScroll.current = scrollToY(element, 0, reduced, () => setMinHeight(undefined));
        else setMinHeight(undefined);
    };
    return { tab, setTab, panel, minHeight, onExitComplete };
}
