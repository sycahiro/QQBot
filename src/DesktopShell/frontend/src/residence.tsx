import { useEffect, useRef, useState } from 'react';
import { Monitor } from 'lucide-react';
import type { DesktopOptions } from './desktop';
import { Notice } from './components/notice';

export function ResidenceSettings({ ready }: { ready: boolean }) {
    const [draft, setDraft] = useState<DesktopOptions | null>(null),
        [busy, setBusy] = useState(false);
    const [error, setError] = useState(''),
        [message, setMessage] = useState('');
    const alive = useRef(true),
        working = useRef(false);
    useEffect(() => {
        alive.current = true;
        if (ready)
            void window
                .pywebview!.api.get_desktop_options()
                .then((result) => {
                    if (!alive.current) return;
                    if (result.ok) setDraft(result.options);
                    else setError(result.error.message);
                })
                .catch(() => {
                    if (alive.current) setError('桌面设置读取失败，请重新打开本页');
                });
        return () => {
            alive.current = false;
        };
    }, [ready]);
    const change = async (patch: Partial<DesktopOptions>) => {
        if (!draft || working.current) return;
        const previous = draft,
            next = { ...draft, ...patch };
        working.current = true;
        setDraft(next);
        setBusy(true);
        setError('');
        setMessage('');
        try {
            const { trayReady: _, ...options } = next;
            const result = await window.pywebview!.api.save_desktop_options(options);
            if (!alive.current) return;
            if (result.ok) {
                setDraft(result.options);
                setMessage('设置已生效');
            } else {
                setDraft(previous);
                setError(result.error.message);
            }
        } catch {
            if (!alive.current) return;
            // The write may have completed before the bridge response failed.
            // Re-read once; never repeat a startup-registry mutation blindly.
            try {
                const result = await window.pywebview!.api.get_desktop_options();
                if (alive.current) setDraft(result.ok ? result.options : previous);
            } catch {
                if (alive.current) setDraft(previous);
            }
            if (alive.current) setError('设置结果未确认，请重新打开本页检查');
        } finally {
            working.current = false;
            if (alive.current) setBusy(false);
        }
    };
    return (
        <section className="ui-card console-panel">
            <div className="console-panel-heading">
                <div>
                    <h2>桌面驻留与启动</h2>
                    <p>设置托盘图标和开机启动。</p>
                </div>
                <Monitor size={18} />
            </div>
            <Notice
                title="桌面设置"
                message={error || message}
                error={Boolean(error)}
                onClose={() => {
                    setError('');
                    setMessage('');
                }}
            />
            {draft ? (
                <>
                    <div className="bot-form-grid">
                        <label className="form-wide form-check">
                            <input
                                type="checkbox"
                                checked={draft.trayEnabled}
                                disabled={busy}
                                onChange={(e) => void change({ trayEnabled: e.target.checked })}
                            />
                            显示系统托盘图标
                        </label>
                        <label className="form-wide form-check">
                            <input
                                type="checkbox"
                                checked={draft.startup}
                                disabled={busy}
                                onChange={(e) => void change({ startup: e.target.checked })}
                            />
                            登录 Windows 后自动启动 QQBot
                        </label>
                        <p className="form-wide action-notice">
                            关闭窗口时可选择隐藏或退出；双击托盘图标可恢复窗口。
                        </p>
                    </div>
                </>
            ) : (
                <p className="action-notice">正在读取桌面设置…</p>
            )}
        </section>
    );
}
