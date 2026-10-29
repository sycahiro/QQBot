import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MonitorDown, Power, X } from 'lucide-react';
import { lockModalBackground } from './modal-background';
import { usePresence } from './presence';

export function CloseDialog() {
    const [open, setOpen] = useState(false),
        [busy, setBusy] = useState(false),
        [error, setError] = useState('');
    const dialog = useRef<HTMLDivElement>(null),
        working = useRef(false);
    const previousFocus = useRef<HTMLElement | null>(null);
    const { mounted, leaving } = usePresence(open);
    useEffect(() => {
        const request = () => {
            previousFocus.current = document.activeElement as HTMLElement;
            setError('');
            setOpen(true);
            return true;
        };
        window.__qqbotRequestClose = request;
        return () => {
            if (window.__qqbotRequestClose === request) delete window.__qqbotRequestClose;
        };
    }, []);
    const resolve = async (action: 'cancel' | 'hide' | 'exit') => {
        if (working.current) return;
        working.current = true;
        setBusy(true);
        setError('');
        try {
            const result = await window.pywebview!.api.resolve_window_close(action);
            if (result.ok) setOpen(false);
            else setError(result.error.message);
        } catch {
            setError('操作未完成，请重试或取消');
        } finally {
            working.current = false;
            setBusy(false);
        }
    };
    useEffect(() => {
        if (!open) return;
        const unlock = lockModalBackground(document.getElementById('root'));
        const focusTimer = requestAnimationFrame(() =>
            dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus(),
        );
        const keyboard = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                void resolve('cancel');
            }
            if (event.key === 'Tab') {
                const buttons = Array.from(
                    dialog.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ??
                        [],
                );
                const first = buttons[0],
                    last = buttons.at(-1);
                if (!dialog.current?.contains(document.activeElement)) {
                    event.preventDefault();
                    first?.focus();
                } else if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault();
                    last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault();
                    first?.focus();
                }
            }
        };
        document.addEventListener('keydown', keyboard);
        return () => {
            cancelAnimationFrame(focusTimer);
            document.removeEventListener('keydown', keyboard);
            unlock();
            if (previousFocus.current?.isConnected) previousFocus.current.focus();
        };
    }, [open]);
    if (typeof document === 'undefined' || !mounted) return null;
    return createPortal(
        <div className={'window-dialog-backdrop' + (leaving ? ' is-leaving' : '')}>
            <div
                ref={dialog}
                className="ui-card window-close-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="window-close-title"
            >
                <button
                    className="btn btn-icon window-dialog-dismiss"
                    aria-label="取消关闭"
                    data-cancel
                    disabled={busy}
                    onClick={() => void resolve('cancel')}
                >
                    <X size={18} />
                </button>
                <span className="empty-icon">
                    <MonitorDown size={26} />
                </span>
                <h2 id="window-close-title">关闭 QQBot</h2>
                <p>隐藏到托盘可继续接收消息和运行机器人；退出会停止本应用。</p>
                <div className="window-close-choices">
                    <button className="btn" disabled={busy} onClick={() => void resolve('hide')}>
                        <MonitorDown size={17} />
                        隐藏到托盘
                    </button>
                    <button
                        className="btn btn-primary"
                        disabled={busy}
                        onClick={() => void resolve('exit')}
                    >
                        <Power size={17} />
                        退出应用
                    </button>
                </div>
                {error && (
                    <p className="desktop-error" role="alert">
                        {error}
                    </p>
                )}
            </div>
        </div>,
        document.body,
    );
}
