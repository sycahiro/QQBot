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

    // 幽灵行必须在移除发生的同一次提交里出现。若放到 useEffect 里，effect 在
    // 浏览器绘制之后才跑：移除帧会先画出一帧“行已消失”，下一帧幽灵才补位
    // 撑回原高再收起——肉眼看是内容跳一下再弹回（收起时闪一下）。因此 diff
    // 在渲染期同步完成，React 会把渲染期 setState 合并进同一次提交。
    const current = new Map(entries.map((child) => [getKey(child), child] as const));
    const previous = lastEntries.current;
    if (previous !== current) {
        lastEntries.current = current;
        const removed: { key: string; node: ReactNode }[] = [];
        for (const [key, node] of previous) {
            if (!current.has(key) && !timers.current.has(key)) removed.push({ key, node });
        }
        if (removed.length || ghosts.some((ghost) => current.has(ghost.key))) {
            for (const ghost of ghosts) {
                if (current.has(ghost.key)) {
                    const timer = timers.current.get(ghost.key);
                    if (timer !== undefined) {
                        window.clearTimeout(timer);
                        timers.current.delete(ghost.key);
                    }
                }
            }
            setGhosts((list) => {
                const next = list.filter((ghost) => !current.has(ghost.key));
                for (const item of removed) {
                    if (!next.some((ghost) => ghost.key === item.key)) next.push(item);
                }
                return next;
            });
            for (const { key } of removed) {
                timers.current.set(
                    key,
                    window.setTimeout(() => {
                        timers.current.delete(key);
                        setGhosts((list) => list.filter((ghost) => ghost.key !== key));
                    }, EXIT_MS),
                );
            }
        }
    }
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
