import { useEffect, useRef, useState } from 'react';
import { Sparkles, Check, X, LoaderCircle } from 'lucide-react';
import type { MemoryPreview, MemoryMember } from '../business';
import { Notice } from '../components/notice';
import { Collapse } from '../components/presence';

export function MemoryReview({
    account,
    chatKey,
    member,
    disabled,
    onApplied,
}: {
    account: string;
    chatKey: string;
    member: MemoryMember;
    disabled: boolean;
    onApplied: () => void;
}) {
    const [preview, setPreview] = useState<MemoryPreview | null>(null),
        [text, setText] = useState(''),
        [busy, setBusy] = useState(false),
        [error, setError] = useState('');
    const alive = useRef(true),
        working = useRef(false);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const generate = async () => {
        if (working.current || disabled) return;
        working.current = true;
        setBusy(true);
        setError('');
        setPreview(null);
        try {
            const result = await window.pywebview!.api.preview_memory(
                chatKey,
                member.userId,
                account,
            );
            if (!alive.current) return;
            if (result.ok && result.account === account) {
                setPreview(result.preview);
                setText(result.preview.after.join('\n'));
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (alive.current) setError('整理失败，原记忆未修改，请重试');
        } finally {
            working.current = false;
            if (alive.current) setBusy(false);
        }
    };
    const apply = async () => {
        if (!preview || working.current || disabled) return;
        const values = text
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean);
        working.current = true;
        setBusy(true);
        setError('');
        try {
            const result = await window.pywebview!.api.apply_memory_preview(
                chatKey,
                member.userId,
                preview.token,
                values,
                account,
            );
            if (!alive.current) return;
            if (result.ok && result.account === account) {
                setPreview(null);
                onApplied();
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (alive.current) setError('应用结果未确认，请刷新检查');
        } finally {
            working.current = false;
            if (alive.current) setBusy(false);
        }
    };
    return (
        <div className="memory-review">
            <button className="btn" disabled={disabled || busy} onClick={() => void generate()}>
                {busy ? <LoaderCircle size={15} className="qq-scanning" /> : <Sparkles size={15} />}
                整理预览
            </button>
            <p className="action-notice">让模型整理该成员的记忆，检查结果后确认应用。</p>
            <Notice title="记忆整理" message={error} error onClose={() => setError('')} />
            <Collapse open={Boolean(preview)}>
                <div className="memory-review-content">
                    {preview && (
                        <>
                            <div className="memory-review-heading">
                                <h4>整理结果预览</h4>
                                <small>
                                    {preview.model} · {preview.tokens.toLocaleString()} Token · 参考{' '}
                                    {preview.sourceCount} 条发言 ·{' '}
                                    {Math.ceil(preview.expiresIn / 60)} 分钟内有效
                                </small>
                            </div>
                            <div className="memory-review-grid">
                                <div>
                                    <h4>修改前 · {preview.before.length} 条</h4>
                                    {preview.before.map((value, i) => (
                                        <p key={i}>{value}</p>
                                    ))}
                                </div>
                                <label>
                                    修改后（可编辑，每行一条）
                                    <textarea
                                        rows={6}
                                        value={text}
                                        disabled={busy}
                                        onChange={(e) => setText(e.target.value)}
                                    />
                                </label>
                            </div>
                            <div className="memory-save">
                                <button
                                    className="btn"
                                    disabled={busy}
                                    onClick={() => setPreview(null)}
                                >
                                    <X size={14} />
                                    放弃预览
                                </button>
                                <button
                                    className="btn btn-primary"
                                    disabled={busy || disabled}
                                    onClick={() => void apply()}
                                >
                                    <Check size={14} />
                                    确认应用
                                </button>
                            </div>
                        </>
                    )}
                </div>
            </Collapse>
        </div>
    );
}
