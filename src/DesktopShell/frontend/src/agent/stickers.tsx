import {
    RecordToolbar,
    RecordBrowser,
    RecordCard,
    RecordHeading,
    RecordEmpty,
} from '../components/record-browser';
import { useConfirm } from '../components/confirmation';
import { useEffect, useRef, useState } from 'react';
import { Save, Search, Smile } from 'lucide-react';
import type { Sticker } from '../business';

import { Notice } from '../components/notice';

type Draft = { note: string; tags: string; usage: string };
const draftOf = (item: Sticker): Draft => ({
    note: item.note,
    tags: item.tags.join('，'),
    usage: item.usage,
});

export function Stickers({ ready, account }: { ready: boolean; account: string }) {
    const confirm = useConfirm();
    const [items, setItems] = useState<Sticker[]>([]),
        [chosen, choose] = useState<string | null>(null);
    const [query, setQuery] = useState(''),
        [search, setSearch] = useState(''),
        [revision, refresh] = useState(0);
    const [preview, setPreview] = useState<{ id: string; image: string; item: Sticker } | null>(
        null,
    );
    const [draft, setDraft] = useState<Draft>({ note: '', tags: '', usage: '' });
    const [saved, setSaved] = useState<Draft>(draft);
    const [error, setError] = useState(''),
        [notice, setNotice] = useState(''),
        [loaded, setLoaded] = useState(false),
        [busy, setBusy] = useState(false);
    const mounted = useRef(true),
        working = useRef(false),
        draftRef = useRef(draft);
    draftRef.current = draft;
    const selected = items.some((i) => i.id === chosen) ? chosen : items[0]?.id || null;
    const current = items.find((i) => i.id === selected);
    const selection = useRef(selected);
    selection.current = selected;
    const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    useEffect(() => {
        if (!ready) return;
        let active = true,
            timer: number;
        const read = async () => {
            if (!active) return;
            if (!document.hidden)
                try {
                    const result = await window.pywebview!.api.get_stickers(search, account);
                    if (!active) return;
                    if (result.ok && result.account === account) {
                        setItems(result.items);
                        setLoaded(true);
                        setError('');
                    } else if (!result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('表情库读取失败，请刷新重试');
                }
            if (active) timer = window.setTimeout(read, 3000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, account, search, revision]);
    useEffect(() => {
        setPreview(null);
        setDraft({ note: '', tags: '', usage: '' });
        if (!selected) return;
        let active = true;
        void window
            .pywebview!.api.get_sticker_preview(selected, account)
            .then((result) => {
                if (!active || selection.current !== selected) return;
                if (result.ok && result.account === account) {
                    setPreview({ id: selected, image: result.image, item: result.item });
                    const values = draftOf(result.item);
                    setDraft(values);
                    setSaved(values);
                } else if (!result.ok) setError(result.error.message);
            })
            .catch(() => {
                if (active) setError('表情预览读取失败，请重新选择');
            });
        return () => {
            active = false;
        };
    }, [selected, account]);
    const save = async () => {
        if (!selected || working.current || preview?.id !== selected) return;
        const id = selected,
            snapshot = draft;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.save_sticker(
                id,
                snapshot.note,
                snapshot.tags.split(/[,，\s]+/).filter(Boolean),
                snapshot.usage,
                account,
            );
            if (!mounted.current || selection.current !== id) return;
            if (result.ok && result.account === account) {
                const next = draftOf(result.item);
                setSaved(next);
                if (JSON.stringify(draftRef.current) === JSON.stringify(snapshot)) setDraft(next);
                setNotice('已保存，自动回复已暂停。');
                refresh((v) => v + 1);
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (mounted.current) setError('保存结果未确认，草稿已保留');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const remove = async (all: boolean) => {
        if (working.current || (!all && !selected)) return;
        if (
            !(await confirm(
                all
                    ? `清空当前账号的全部本地收藏表情？此操作无法恢复。`
                    : '删除当前收藏表情？聊天存档不会被删除。',
                {
                    title: all ? '清空表情库' : '删除表情',
                    confirmLabel: all ? '清空全部' : '删除',
                    danger: true,
                },
            ))
        )
            return;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.delete_sticker(
                all ? null : selected,
                account,
            );
            if (!mounted.current) return;
            if (result.ok && result.account === account) {
                setItems((old) => (all ? [] : old.filter((i) => i.id !== selected)));
                choose(null);
                setNotice(`已删除 ${result.deleted} 张表情，自动回复已暂停。`);
                refresh((v) => v + 1);
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (mounted.current) setError('删除结果未确认，请刷新检查');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    return (
        <div className="desktop-sections">
            <Notice
                title={error ? '表情库操作未完成' : '表情库'}
                message={error || notice}
                error={Boolean(error)}
                onClose={() => {
                    setError('');
                    setNotice('');
                }}
            />
            <RecordToolbar
                summary="管理当前账号收藏的表情。"
                noun="表情"
                remove={{ disabled: busy || !selected, run: () => void remove(false) }}
                clear={{ disabled: busy || !items.length, run: () => void remove(true) }}
                refresh={{ disabled: busy, run: () => refresh((v) => v + 1) }}
            />
            <form
                className="archive-search"
                role="search"
                aria-label="搜索表情库"
                onSubmit={async (event) => {
                    event.preventDefault();
                    if (
                        !dirty ||
                        (await confirm('搜索会切换表情，当前未保存的备注修改将被放弃。', {
                            title: '放弃备注修改',
                            confirmLabel: '放弃并搜索',
                        }))
                    )
                        setSearch(query.trim());
                }}
            >
                <label className="archive-search-input">
                    <Search size={16} />
                    <input
                        aria-label="搜索表情备注与标签"
                        value={query}
                        maxLength={120}
                        placeholder="搜索备注、标签或使用场景…"
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </label>
                <button className="qq-refresh" type="submit">
                    搜索
                </button>
            </form>
            {!items.length ? (
                <RecordEmpty
                    icon={<Smile size={28} />}
                    title={
                        loaded ? (search ? '没有匹配的表情' : '还没有收藏表情') : '正在读取表情库'
                    }
                >
                    <p>在聊天存档中点击“收藏首张图片”即可添加表情。</p>
                    <p>也可在机器人设置中允许模型收藏。</p>
                </RecordEmpty>
            ) : (
                <RecordBrowser
                    identity={`${account}|${selected}`}
                    list={[
                        items.map((item) => (
                            <RecordCard
                                key={item.id}
                                disabled={busy}
                                selected={selected === item.id}
                                onSelect={async () => {
                                    if (
                                        item.id === selected ||
                                        !dirty ||
                                        (await confirm('切换表情会放弃当前未保存的备注修改。', {
                                            title: '放弃备注修改',
                                            confirmLabel: '放弃并切换',
                                        }))
                                    )
                                        choose(item.id);
                                }}
                                title={item.note || '未备注的表情'}
                                subtitle={
                                    <>
                                        {item.width} × {item.height} ·{' '}
                                        {(item.bytes / 1024).toFixed(1)} KB
                                    </>
                                }
                                preview={
                                    <>
                                        {item.tags.join(' · ') || item.usage || '暂无标签'} · 已使用{' '}
                                        {item.uses} 次
                                    </>
                                }
                            />
                        )),
                    ]}
                >
                    <RecordHeading
                        title={current?.note || '收藏表情'}
                        subtitle="预览图片并编辑备注。"
                        icon={<Smile size={18} />}
                    />
                    {preview?.id === selected ? (
                        <>
                            <div className="sticker-preview">
                                <img src={preview.image} alt={current?.note || '收藏表情'} />
                            </div>
                            <p className="action-notice sticker-meta">
                                {preview.item.width} × {preview.item.height} ·{' '}
                                {(preview.item.bytes / 1024).toFixed(1)} KB
                                {preview.item.firstFrame ? ' · 动图首帧' : ''} ·{' '}
                                {new Date(preview.item.created).toLocaleString('zh-CN', {
                                    hour12: false,
                                })}
                            </p>
                            <div className="bot-form-grid">
                                <label className="form-wide">
                                    表情备注
                                    <input
                                        maxLength={120}
                                        value={draft.note}
                                        onChange={(e) =>
                                            setDraft({ ...draft, note: e.target.value })
                                        }
                                        placeholder="例如：开心点头、无语、震惊"
                                    />
                                </label>
                                <label className="form-wide">
                                    标签
                                    <input
                                        maxLength={180}
                                        value={draft.tags}
                                        onChange={(e) =>
                                            setDraft({ ...draft, tags: e.target.value })
                                        }
                                        placeholder="用逗号或空格分隔，最多 8 项"
                                    />
                                </label>
                                <label className="form-wide">
                                    使用场景
                                    <input
                                        maxLength={120}
                                        value={draft.usage}
                                        onChange={(e) =>
                                            setDraft({ ...draft, usage: e.target.value })
                                        }
                                        placeholder="例如：赞同群友、轻松调侃"
                                    />
                                </label>
                            </div>
                            <div className="card-save-footer save-actions">
                                <button
                                    className="qq-refresh primary-button"
                                    disabled={busy || !dirty}
                                    onClick={() => void save()}
                                >
                                    <Save size={14} />
                                    保存
                                </button>
                            </div>
                        </>
                    ) : (
                        <p className="action-notice">正在读取图片预览…</p>
                    )}
                </RecordBrowser>
            )}
        </div>
    );
}
