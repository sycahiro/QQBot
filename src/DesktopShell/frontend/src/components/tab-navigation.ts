import { useEffect, useRef, useState } from 'react';
import { scrollToY } from '../motion';

/** Switch tabs instantly, then glide the main scroller back to the top. */
export function useTabNavigation<T extends string>(initial: T) {
    const [tab, change] = useState(initial);
    const panel = useRef<HTMLDivElement>(null),
        cancelScroll = useRef<(() => void) | null>(null);
    const first = useRef(true);
    useEffect(() => () => cancelScroll.current?.(), []);
    useEffect(() => {
        if (first.current) {
            first.current = false;
            return;
        }
        cancelScroll.current?.();
        const element = document.getElementById('main-content');
        if (element) cancelScroll.current = scrollToY(element, 0);
    }, [tab]);
    return { tab, setTab: change, panel };
}
