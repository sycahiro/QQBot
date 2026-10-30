import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, ExternalLink, KeyRound, Save, Trash2 } from 'lucide-react';
import { Notice } from '../components/notice';

export function EngineSettings({ ready }: { ready: boolean }) {
    const [webuiBusy, setWebuiBusy] = useState(false);
    const [notice, setNotice] = useState(''),
        [error, setError] = useState('');
    const openWebui = async () => {
        setWebuiBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.open_snowluma_webui();
            if (result.ok) setNotice('已在系统浏览器打开 SnowLuma 控制台。');
            else setError(result.error.message);
        } catch {
            setError('打开 WebUI 未完成，请重试');
        } finally {
            setWebuiBusy(false);
        }
    };
    return (
        <div className="desktop-sections">
            <Notice
                message={error || notice}
                error={Boolean(error)}
                onClose={() => {
                    setNotice('');
                    setError('');
                }}
            />
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>SnowLuma WebUI</h2>
                        <p>
                            引擎自带的控制台。模型接入、记忆、扩展、引擎更新等一切引擎事务都在它自己的
                            WebUI 里完成，本应用只负责启动与连接，不代管引擎配置。
                        </p>
                    </div>
                    <ExternalLink size={18} />
                </div>
                <div className="webui-access">
                    <div className="webui-access-main">
                        <button
                            className="btn btn-primary"
                            disabled={webuiBusy || !ready}
                            onClick={() => void openWebui()}
                        >
                            <ExternalLink size={15} />
                            {webuiBusy ? '正在打开…' : '打开 WebUI'}
                        </button>
                        <code className="webui-url">http://127.0.0.1:5099</code>
                    </div>
                    <small className="webui-hint">
                        登录密码以你在 WebUI 里设置的为准；懒得记就存到下面的密码备忘。
                    </small>
                </div>
            </section>
            <PasswordMemo />
        </div>
    );
}

/** 手动保存的密码备忘（SnowLuma 控制台密码），仅存本机。 */
function PasswordMemo() {
    const [saved, setSaved] = useState<string | null>(null);
    const [draft, setDraft] = useState('');
    const [editing, setEditing] = useState(false);
    const [revealed, setRevealed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    const load = async () => {
        try {
            const result = await window.pywebview!.api.get_webui_password_memo();
            if (!mounted.current) return;
            if (result.ok) setSaved(result.password);
            else setError(result.error.message);
        } catch {
            if (mounted.current) setError('密码备忘暂时无法读取');
        }
    };
    useEffect(() => {
        void load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    const save = async (value: string) => {
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.save_webui_password_memo(value);
            if (!mounted.current) return;
            if (result.ok) {
                setSaved(result.password);
                setEditing(false);
                setRevealed(false);
                setDraft('');
                setNotice(value ? '密码已保存到本机。' : '已清除保存的密码。');
            } else setError(result.error.message);
        } catch {
            if (mounted.current) setError('保存未完成，请重试');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    const copy = async () => {
        if (!saved) return;
        try {
            await navigator.clipboard.writeText(saved);
        } catch {
            // pywebview 环境下 Clipboard API 可能不可用；回退到隐藏文本域复制。
            const area = document.createElement('textarea');
            area.value = saved;
            area.setAttribute('readonly', '');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            let ok = false;
            try {
                ok = document.execCommand('copy');
            } catch {
                ok = false;
            }
            document.body.removeChild(area);
            if (!ok) {
                if (mounted.current) setError('复制失败，请显示密码后手动复制');
                return;
            }
        }
        if (mounted.current) {
            setError('');
            setCopied(true);
            window.setTimeout(() => {
                if (mounted.current) setCopied(false);
            }, 2000);
        }
    };
    return (
        <section className="ui-card console-panel password-memo">
            <div className="console-panel-heading">
                <div>
                    <h2>密码备忘</h2>
                    <p>
                        手动保存 SnowLuma 控制台的登录密码，仅存放在本机
                        runtime/secrets，不会上传；应用不会代读或代改引擎凭据。
                    </p>
                </div>
                <KeyRound size={18} />
            </div>
            {saved && !editing ? (
                <div className="memo-body" key="view">
                    <code className="memo-secret-value">
                        {revealed ? saved : '•'.repeat(Math.min(saved.length, 20))}
                    </code>
                    <div className="memo-actions">
                        <button
                            className="btn btn-sm"
                            onClick={() => setRevealed((value) => !value)}
                        >
                            {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
                            {revealed ? '隐藏' : '显示'}
                        </button>
                        <button className="btn btn-sm" onClick={() => void copy()}>
                            {copied ? '已复制' : '复制'}
                        </button>
                        <button
                            className="btn btn-sm"
                            onClick={() => {
                                setEditing(true);
                                setDraft(saved);
                                setNotice('');
                            }}
                        >
                            修改
                        </button>
                    </div>
                </div>
            ) : (
                <div className="memo-body" key="edit">
                    <input
                        type={revealed ? 'text' : 'password'}
                        value={draft}
                        placeholder={saved ? '输入新的密码' : '输入要保存的密码'}
                        maxLength={200}
                        disabled={busy}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && draft.trim()) void save(draft);
                        }}
                    />
                    <div className="memo-actions">
                        <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => setRevealed((value) => !value)}
                        >
                            {revealed ? <EyeOff size={13} /> : <Eye size={13} />}
                            {revealed ? '隐藏' : '显示'}
                        </button>
                        <button
                            className="btn btn-sm btn-primary"
                            disabled={busy || !draft.trim()}
                            onClick={() => void save(draft)}
                        >
                            <Save size={13} />
                            保存
                        </button>
                        {editing && (
                            <button
                                className="btn btn-sm"
                                disabled={busy}
                                onClick={() => {
                                    setEditing(false);
                                    setDraft('');
                                }}
                            >
                                取消
                            </button>
                        )}
                    </div>
                </div>
            )}
            {saved && !editing && (
                <button
                    className="btn btn-sm memo-clear"
                    disabled={busy}
                    onClick={() => void save('')}
                >
                    <Trash2 size={13} />
                    清除保存的密码
                </button>
            )}
            {error && (
                <p className="desktop-error" role="alert">
                    {error}
                </p>
            )}
            {notice && !error && <p className="action-notice">{notice}</p>}
        </section>
    );
}
