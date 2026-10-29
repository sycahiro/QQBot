import { useEffect, useRef, useState, type ReactNode } from 'react';
import { UI_MOTION } from '../motion';

const EXIT_MS = UI_MOTION.duration * 1000;

export type Presence = { mounted: boolean; leaving: boolean };

/** Keeps an element mounted through its CSS exit animation after `open` turns false. */
export function usePresence(open: boolean, exitMs = EXIT_MS): Presence {
    const [presence, setPresence] = useState<Presence>({ mounted: open, leaving: false });
    const mountedRef = useRef(open);
    useEffect(() => {
        if (open) {
            mountedRef.current = true;
            setPresence({ mounted: true, leaving: false });
            return;
        }
        if (!mountedRef.current) return;
        setPresence({ mounted: true, leaving: true });
        const timer = window.setTimeout(() => {
            mountedRef.current = false;
            setPresence({ mounted: false, leaving: false });
        }, exitMs);
        return () => window.clearTimeout(timer);
    }, [open, exitMs]);
    return presence;
}

/** Grid-rows collapse container; content stays mounted while collapsing. */
export function Collapse({
    open,
    children,
    className = '',
}: {
    open: boolean;
    children: ReactNode;
    className?: string;
}) {
    const frozen = useRef<ReactNode>(null);
    if (open || frozen.current === null) frozen.current = children;
    return (
        <div
            className={'ui-collapse' + (className ? ' ' + className : '')}
            data-open={open || undefined}
            inert={!open || undefined}
        >
            <div className="ui-collapse-clip">{frozen.current}</div>
        </div>
    );
}
