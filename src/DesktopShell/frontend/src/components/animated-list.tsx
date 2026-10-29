import { Children, useEffect, useRef, useState, type ReactNode } from 'react';
import { UI_MOTION } from '../motion';

const EXIT_MS = UI_MOTION.duration * 1000;

/**
 * Animate keyed entries, not the polling response or the whole page.
 * New rows expand via CSS keyframes; removed rows stay as ghosts for one
 * motion cycle so the browser can animate their collapse.
 */
export function AnimatedList({
    children,
    className,
    staged = false,
}: {
    children: ReactNode;
    className?: string;
    staged?: boolean;
}) {
    const entries = Children.toArray(children);
    const getKey = (child: (typeof entries)[number]): string =>
        typeof child === 'object' && 'key' in child ? String(child.key ?? child) : String(child);
    const firstKeys = useRef<Set<string> | null>(null);
    if (entries.length && firstKeys.current === null)
        firstKeys.current = new Set(entries.map(getKey));
    const [ghosts, setGhosts] = useState<{ key: string; node: ReactNode }[]>([]);
    const lastEntries = useRef<Map<string, ReactNode>>(new Map());
    const timers = useRef(new Map<string, number>());
    const signature = entries.map(getKey).join('\u0000');
    useEffect(() => {
        const current = new Map(entries.map((child) => [getKey(child), child] as const));
        const previous = lastEntries.current;
        lastEntries.current = current;
        setGhosts((list) => {
            const kept = list.filter((ghost) => current.has(ghost.key));
            return kept.length === list.length ? list : kept;
        });
        for (const [key, node] of previous) {
            if (current.has(key) || timers.current.has(key)) continue;
            setGhosts((list) => [...list, { key, node }]);
            timers.current.set(
                key,
                window.setTimeout(() => {
                    timers.current.delete(key);
                    setGhosts((list) => list.filter((ghost) => ghost.key !== key));
                }, EXIT_MS),
            );
        }
    }, [signature]);
    useEffect(
        () => () => {
            for (const timer of timers.current.values()) window.clearTimeout(timer);
        },
        [],
    );
    const initial = firstKeys.current;
    return (
        <div
            className={
                'animated-list' +
                (className ? ' ' + className : '') +
                (staged ? ' is-staged' : '') +
                (staged && !entries.length ? ' is-empty' : '')
            }
        >
            {entries.map((child) => {
                const key = getKey(child);
                const initialBatch = initial?.has(key);
                return (
                    <div
                        className="animated-list-item"
                        key={key}
                        data-static={initialBatch || undefined}
                    >
                        <div className="animated-list-clip">
                            <div
                                className="animated-list-content"
                                data-slide={staged && !initialBatch ? '' : undefined}
                            >
                                {child}
                            </div>
                        </div>
                    </div>
                );
            })}
            {ghosts.map((ghost) => (
                <div
                    className="animated-list-item is-ghost"
                    key={'ghost-' + String(ghost.key)}
                    aria-hidden="true"
                >
                    <div className="animated-list-clip">
                        <div className="animated-list-content">{ghost.node}</div>
                    </div>
                </div>
            ))}
        </div>
    );
}
