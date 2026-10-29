import { useEffect, useRef } from 'react';

/** Single sliding nav highlight: measures the active item, CSS animates `top`. */
export function useNavHighlight(active: string) {
    const navRef = useRef<HTMLElement>(null);
    const highlightRef = useRef<HTMLSpanElement>(null);
    useEffect(() => {
        const nav = navRef.current,
            highlight = highlightRef.current;
        if (!nav || !highlight) return;
        const item = nav.querySelector<HTMLElement>('[aria-current="page"]');
        if (!item) {
            delete highlight.dataset.ready;
            return;
        }
        const navBox = nav.getBoundingClientRect(),
            box = item.getBoundingClientRect();
        highlight.style.top = `${box.top - navBox.top}px`;
        highlight.style.height = `${box.height}px`;
        highlight.style.left = `${box.left - navBox.left}px`;
        highlight.style.width = `${box.width}px`;
        highlight.dataset.ready = 'true';
    }, [active]);
    return { navRef, highlightRef };
}
