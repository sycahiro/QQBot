import { uiTransition } from '../motion';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { CheckCircle2, CircleAlert, X } from 'lucide-react';
import {
    addNotice,
    dismissNotice,
    getNotices,
    getServerNotices,
    subscribeNotices,
    type NoticeEntry,
} from './notice-store';

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
    if (typeof document === 'undefined') return null;
    return createPortal(
        <div className="notice-host" aria-label="通知">
            <AnimatePresence initial={false}>
                {entries.map((entry) => (
                    <NoticeCard key={entry.id} entry={entry} />
                ))}
            </AnimatePresence>
        </div>,
        document.body,
    );
}
function NoticeCard({ entry }: { entry: NoticeEntry }) {
    const reduced = useReducedMotion();
    const [hovered, setHovered] = useState(false),
        [focused, setFocused] = useState(false);
    const paused = hovered || focused;
    const remaining = useRef(entry.error ? 7000 : 5000);
    useEffect(() => {
        if (paused) return;
        const started = performance.now();
        const timer = window.setTimeout(() => dismissNotice(entry.id), remaining.current);
        return () => {
            window.clearTimeout(timer);
            remaining.current = Math.max(0, remaining.current - (performance.now() - started));
        };
    }, [entry.id, paused]);
    const Icon = entry.error ? CircleAlert : CheckCircle2;
    return (
        <motion.div
            layout="position"
            className={`ui-notice${entry.error ? ' is-error' : ''}`}
            initial={{ opacity: 0, x: reduced ? 0 : 72, y: 0 }}
            animate={{ opacity: 1, x: 0, y: 0 }}
            exit={{ opacity: 0, x: 0, y: reduced ? 0 : 40 }}
            transition={uiTransition(reduced)}
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
            <button type="button" aria-label="关闭通知" onClick={() => dismissNotice(entry.id)}>
                <X size={16} />
            </button>
        </motion.div>
    );
}
