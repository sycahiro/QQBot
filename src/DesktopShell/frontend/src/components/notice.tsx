import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, CircleAlert, X } from 'lucide-react';
import {
    addNotice,
    dismissNotice,
    getNotices,
    getServerNotices,
    subscribeNotices,
    type NoticeEntry,
} from './notice-store';
import { UI_MOTION } from '../motion';

const EXIT_MS = UI_MOTION.duration * 1000;

/** Pages publish notifications; one app-level host owns order, timers and motion. */
export function Notice({
    message,
    error = false,
    onClose,
    title,
}: {
    message: string;
    error?: boolean;
    onClose: () => void;
    title?: string;
}) {
    const callback = useRef(onClose),
        current = useRef<symbol | null>(null);
    callback.current = onClose;
    useEffect(() => {
        if (!message) return;
        const token = Symbol('notice');
        current.current = token;
        addNotice({
            message,
            error,
            title,
            onClose: () => {
                if (current.current === token) callback.current();
            },
        });
        return () => {
            current.current = null;
        };
    }, [message, error, title]);
    return null;
}
export function NoticeHost() {
    const entries = useSyncExternalStore(subscribeNotices, getNotices, getServerNotices);
    const [ghosts, setGhosts] = useState<NoticeEntry[]>([]);
    const lastEntries = useRef<Map<number, NoticeEntry>>(new Map());
    const timers = useRef(new Map<number, number>());
    const signature = entries.map((entry) => String(entry.id)).join('|');
    useEffect(() => {
        const current = new Set(entries.map((entry) => entry.id));
        const previous = lastEntries.current;
        lastEntries.current = new Map(entries.map((entry) => [entry.id, entry] as const));
        setGhosts((list) => {
            const kept = list.filter((ghost) => current.has(ghost.id));
            return kept.length === list.length ? list : kept;
        });
        for (const [id, entry] of previous) {
            if (current.has(id) || timers.current.has(id)) continue;
            setGhosts((list) => [...list, entry]);
            timers.current.set(
                id,
                window.setTimeout(() => {
                    timers.current.delete(id);
                    setGhosts((list) => list.filter((ghost) => ghost.id !== id));
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
    if (typeof document === 'undefined') return null;
    return createPortal(
        <div className="notice-host" aria-label="通知">
            {entries.map((entry) => (
                <NoticeCard key={entry.id} entry={entry} />
            ))}
            {ghosts.map((entry) => (
                <NoticeCard key={'ghost-' + String(entry.id)} entry={entry} ghost />
            ))}
        </div>,
        document.body,
    );
}
function NoticeCard({ entry, ghost = false }: { entry: NoticeEntry; ghost?: boolean }) {
    const [hovered, setHovered] = useState(false),
        [focused, setFocused] = useState(false);
    const paused = hovered || focused;
    const remaining = useRef(entry.error ? 7000 : 5000);
    useEffect(() => {
        if (ghost || paused) return;
        const started = performance.now();
        const timer = window.setTimeout(() => dismissNotice(entry.id), remaining.current);
        return () => {
            window.clearTimeout(timer);
            remaining.current = Math.max(0, remaining.current - (performance.now() - started));
        };
    }, [entry.id, paused, ghost]);
    const Icon = entry.error ? CircleAlert : CheckCircle2;
    return (
        <div
            className={`ui-notice${entry.error ? ' is-error' : ''}${ghost ? ' is-leaving' : ''}`}
            role={entry.error ? 'alert' : 'status'}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            onFocusCapture={() => setFocused(true)}
            onBlurCapture={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
            }}
        >
            <Icon size={19} />
            <div>
                <strong>{entry.title || (entry.error ? '操作未完成' : '操作完成')}</strong>
                <p>{entry.message}</p>
            </div>
            <button
                type="button"
                className="btn btn-bare"
                aria-label="关闭通知"
                onClick={() => dismissNotice(entry.id)}
            >
                <X size={16} />
            </button>
        </div>
    );
}
