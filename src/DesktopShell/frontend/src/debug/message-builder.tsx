import { useState, useEffect, useRef, type Dispatch, type SetStateAction } from 'react';
import { Plus, Trash2, ArrowUp, ArrowDown, Paperclip } from 'lucide-react';
import { AnimatedList } from '../components/animated-list';
import { Select } from '../components/select';
import { newSegment, type Segment } from './builder';

const kinds = [
    ['text', '文字'],
    ['image', '图片'],
    ['face', 'QQ 表情'],
    ['at', '群提及 @'],
    ['reply', '引用消息'],
    ['record', '语音'],
    ['video', '视频'],
    ['file', '文件'],
] as const;
export function MessageBuilder({
    account,
    segments,
    onChange,
    forward,
    busy,
    onError,
}: {
    account: string;
    segments: Segment[];
    onChange: Dispatch<SetStateAction<Segment[]>>;
    forward: boolean;
    busy: boolean;
    onError: (s: string) => void;
}) {
    const [adding, setAdding] = useState('');
    const alive = useRef(true);
    useEffect(() => {
        alive.current = true;
        return () => {
            alive.current = false;
        };
    }, []);
    const change = (id: string, patch: Partial<Segment>) =>
        onChange((values) => values.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    const discard = (item: Segment) => {
        if (item.attachment)
            void window.pywebview!.api.discard_debug_file(item.attachment.token, account);
    };
    const move = (index: number, delta: number) =>
        onChange((values) => {
            const copy = [...values];
            [copy[index], copy[index + delta]] = [copy[index + delta], copy[index]];
            return copy;
        });
    const pick = async (item: Segment, file?: File) => {
        if (!file || adding || busy) return;
        if (file.size > 8 * 1024 * 1024) {
            onError('单个附件最大为 8 MB');
            return;
        }
        setAdding(item.id);
        onError('');
        try {
            const encoded = await new Promise<string>((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result).split(',')[1]);
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
            const result = await window.pywebview!.api.stage_debug_file(
                item.type,
                file.name,
                encoded,
                account,
            );
            if (!alive.current) {
                if (result.ok)
                    void window.pywebview!.api.discard_debug_file(result.attachment.token, account);
                return;
            }
            if (result.ok && result.account === account) {
                discard(item);
                change(item.id, { attachment: result.attachment });
            } else if (!result.ok) onError(result.error.message);
        } catch {
            if (alive.current) onError('附件读取失败，请重新选择');
        } finally {
            if (alive.current) setAdding('');
        }
    };
    return (
        <div className="desktop-sections">
            <p className="action-notice">
                {forward
                    ? '每个片段作为一条转发消息，最多 5 条，支持文字、图片和表情。'
                    : '按顺序组合消息片段。语音、视频和文件各自单独发送；引用必须放在第一项。'}{' '}
                附件最大 8 MB。
            </p>
            <AnimatedList className="desktop-sections">
                {segments.map((item, index) => (
                    <section className="session-record debug-segment" key={item.id}>
                        <div className="debug-segment-heading">
                            <strong>片段 {index + 1}</strong>
                            <div className="debug-segment-tools">
                                <button
                                    className="qq-refresh"
                                    disabled={busy || index === 0 || Boolean(adding)}
                                    aria-label={`上移片段${index + 1}`}
                                    onClick={() => move(index, -1)}
                                >
                                    <ArrowUp size={13} />
                                </button>
                                <button
                                    className="qq-refresh"
                                    disabled={
                                        busy || index === segments.length - 1 || Boolean(adding)
                                    }
                                    aria-label={`下移片段${index + 1}`}
                                    onClick={() => move(index, 1)}
                                >
                                    <ArrowDown size={13} />
                                </button>
                                <button
                                    className="qq-refresh"
                                    disabled={busy || segments.length === 1 || Boolean(adding)}
                                    onClick={() => {
                                        discard(item);
                                        onChange((values) =>
                                            values.filter((s) => s.id !== item.id),
                                        );
                                    }}
                                >
                                    <Trash2 size={13} />
                                    移除
                                </button>
                            </div>
                        </div>
                        <div className="bot-form-grid">
                            <div className="bot-field">
                                <span>片段类型</span>
                                <Select
                                    label={`片段${index + 1}类型`}
                                    value={item.type}
                                    disabled={busy || Boolean(adding)}
                                    options={kinds
                                        .filter(
                                            ([id]) =>
                                                !forward || ['text', 'image', 'face'].includes(id),
                                        )
                                        .map(([value, label]) => ({ value, label }))}
                                    onChange={(value) => {
                                        discard(item);
                                        change(item.id, {
                                            type: value as Segment['type'],
                                            value: '',
                                            attachment: undefined,
                                        });
                                    }}
                                />
                            </div>
                            {item.type === 'text' ? (
                                <label className="form-wide">
                                    文字
                                    <textarea
                                        rows={3}
                                        maxLength={3000}
                                        disabled={busy}
                                        value={item.value}
                                        onChange={(e) => change(item.id, { value: e.target.value })}
                                    />
                                </label>
                            ) : ['at', 'reply', 'face'].includes(item.type) ? (
                                <label>
                                    {item.type === 'at'
                                        ? '成员 QQ 号'
                                        : item.type === 'reply'
                                          ? '当前聊天消息编号'
                                          : 'QQ 表情编号'}
                                    <input
                                        disabled={busy}
                                        value={item.value}
                                        onChange={(e) => change(item.id, { value: e.target.value })}
                                    />
                                </label>
                            ) : (
                                <label className="debug-file-picker">
                                    <span>
                                        <Paperclip size={14} />{' '}
                                        {adding === item.id
                                            ? '正在暂存…'
                                            : item.attachment
                                              ? `${item.attachment.name} · ${(item.attachment.bytes / 1024).toFixed(1)} KB`
                                              : '选择附件'}
                                    </span>
                                    <input
                                        type="file"
                                        disabled={busy || Boolean(adding)}
                                        aria-label={`选择片段${index + 1}附件`}
                                        accept={
                                            item.type === 'image'
                                                ? 'image/jpeg,image/png,image/webp,image/gif'
                                                : item.type === 'video'
                                                  ? '.mp4,.mov,.webm,.mkv'
                                                  : item.type === 'record'
                                                    ? '.wav,.mp3,.ogg,.silk,.amr'
                                                    : undefined
                                        }
                                        onChange={(e) => {
                                            void pick(item, e.target.files?.[0]);
                                            e.target.value = '';
                                        }}
                                    />
                                </label>
                            )}
                        </div>
                    </section>
                ))}
            </AnimatedList>
            <button
                className="qq-refresh"
                disabled={busy || Boolean(adding) || segments.length >= (forward ? 5 : 16)}
                onClick={() => onChange((values) => [...values, newSegment()])}
            >
                <Plus size={14} />
                添加片段{forward ? '／转发节点' : ''}
            </button>
        </div>
    );
}
