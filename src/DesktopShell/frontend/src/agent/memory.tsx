import {
    RecordToolbar,
    RecordBrowser,
    RecordCard,
    RecordHeading,
    RecordEmpty,
} from '../components/record-browser';
import { useConfirm } from '../components/confirmation';
import { useEffect, useRef, useState } from 'react';
import { AnimatedList } from '../components/animated-list';
import { Brain, Save, Trash2 } from 'lucide-react';
import { chatLabel, type MemoryChat, type MemoryMember } from '../business';
import { MemoryReview } from './memory-review';
import { Notice } from '../components/notice';

export function Memory({ ready }: { ready: boolean }) {
    const confirm = useConfirm();
    const [account, setAccount] = useState<string | null>(null);
    const [chats, setChats] = useState<MemoryChat[]>([]);
    const [chosen, choose] = useState<string | null>(null);
    const [members, setMembers] = useState<MemoryMember[]>([]);
    const [detailKey, setDetailKey] = useState('');
    const [drafts, setDrafts] = useState<Record<string, string>>({});
    const hasDrafts = Object.keys(drafts).length > 0;
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [revision, refresh] = useState(0);
    const selected = chats.some((c) => c.chatKey === chosen) ? chosen : chats[0]?.chatKey;
    const current = chats.find((c) => c.chatKey === selected);
    const marker = useRef('');
    const dirty = useRef(false);
    useEffect(() => {
        dirty.current = Object.keys(drafts).length > 0;
    }, [drafts]);
    const mounted = useRef(true),
        working = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    const markerValue = `${account}|${selected}`;
    marker.current = markerValue;
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const read = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const result = await window.pywebview!.api.get_memory_chats();
                    if (active && result.ok) {
                        setAccount(result.account);
                        setChats(result.items);
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('记忆列表读取失败');
                }
            }
            if (active) timer = window.setTimeout(read, 3000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, revision]);
    useEffect(() => {
        setDrafts({});
        dirty.current = false;
    }, [account, selected]);
    useEffect(() => {
        if (!ready || !selected || !account) return;
        let active = true;
        let timer: number;
        const expected = `${account}|${selected}`;
        const read = async () => {
            if (!active) return;
            if (!document.hidden && !dirty.current) {
                try {
                    const result = await window.pywebview!.api.get_memories(selected);
                    if (
                        active &&
                        marker.current === expected &&
                        !dirty.current &&
                        result.ok &&
                        result.account === account
                    ) {
                        setMembers(result.members);
                        setDetailKey(expected);
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('成员记忆读取失败');
                }
            }
            if (active) timer = window.setTimeout(read, 3000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, selected, account, revision]);
    const save = async (member: MemoryMember) => {
        if (!account || !selected || working.current || detailKey !== marker.current) return;
        const expected = marker.current;
        const current = () => mounted.current && marker.current === expected;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const text = drafts[member.userId] ?? member.entries.map((e) => e.content).join('\n');
            const result = await window.pywebview!.api.save_memory(
                selected,
                member.userId,
                member.target,
                text.split('\n').filter((v) => v.trim()),
                account,
            );
            if (!current()) return;
            if (result.ok && result.account === account) {
                const latest = await window.pywebview!.api.get_memories(selected);
                if (!current()) return;
                if (latest.ok && latest.account === account) setMembers(latest.members);
                setNotice('成员记忆已保存；如需继续处理新消息，请重新开启自动回复。');
                setDrafts((values) => {
                    const next = { ...values };
                    delete next[member.userId];
                    return next;
                });
                refresh((v) => v + 1);
            } else setError(result.ok ? '连接账号已变化，请重新打开记忆' : result.error.message);
        } catch {
            if (current()) setError('保存结果未确认，请刷新检查');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const remove = async (all: boolean, member?: MemoryMember) => {
        if (!account || working.current || (!all && !selected)) return;
        const expected = marker.current;
        const currentView = () => mounted.current && marker.current === expected;
        const label = all
            ? `当前账号的全部记忆`
            : member
              ? `${member.target || member.userId} 的记忆`
              : `${current ? chatLabel(current).title : '当前聊天'}的全部记忆`;
        working.current = true;
        try {
            if (
                !(await confirm(`确定删除${label}？此操作不会删除聊天存档和会话日志。`, {
                    title: all ? '清空全部记忆' : '删除记忆',
                    confirmLabel: all ? '清空全部' : '删除',
                    danger: true,
                })) ||
                !currentView()
            )
                return;
            setBusy(true);
            setError('');
            setNotice('');
            const result = await window.pywebview!.api.delete_memory(
                all ? null : selected!,
                member?.userId ?? null,
                account,
            );
            if (!currentView()) return;
            if (result.ok && result.account === account) {
                setNotice(`已删除 ${result.deleted} 条记忆`);
                dirty.current = false;
                setDrafts({});
                setMembers([]);
                refresh((v) => v + 1);
            } else setError(result.ok ? '连接账号已变化，请重新打开记忆' : result.error.message);
        } catch {
            if (currentView()) setError('删除结果未确认，请刷新检查');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const visible = detailKey === markerValue ? members : [];
    const group = selected?.startsWith('group:');
    return (
        <div className="desktop-sections">
            <RecordToolbar
                summary="查看和编辑成员的长期记忆，每行一条。"
                noun="记忆"
                removeLabel="删除当前聊天记忆"
                remove={{ disabled: busy || !current?.count, run: () => void remove(false) }}
                clear={{
                    disabled: busy || !chats.some((c) => c.count),
                    run: () => void remove(true),
                }}
                refresh={{ disabled: busy || hasDrafts, run: () => refresh((v) => v + 1) }}
            />
            <Notice title="记忆操作" message={error} error onClose={() => setError('')} />
            <Notice title="记忆操作" message={notice} onClose={() => setNotice('')} />
            {!chats.length ? (
                <RecordEmpty icon={<Brain size={28} />} title="还没有成员记忆">
                    <p>模型记录的长期印象会显示在这里。</p>
                </RecordEmpty>
            ) : (
                <RecordBrowser
                    identity={markerValue}
                    list={[
                        chats.map((chat) => (
                            <RecordCard
                                key={chat.chatKey}
                                disabled={busy}
                                selected={selected === chat.chatKey}
                                onSelect={() => {
                                    if (!working.current) choose(chat.chatKey);
                                }}
                                title={chatLabel(chat).title}
                                subtitle={chatLabel(chat).number}
                                preview={
                                    <>
                                        {chat.members} 位成员 · {chat.count} 条记忆
                                    </>
                                }
                            />
                        )),
                    ]}
                >
                    <RecordHeading
                        title={current ? chatLabel(current).title : ''}
                        subtitle={current ? chatLabel(current).number : ''}
                        icon={<Brain size={18} />}
                    />
                    {!visible.length ? (
                        <div className="desktop-empty">
                            <h3>{detailKey !== markerValue ? '正在读取记忆…' : '暂无长期印象'}</h3>
                            <p>模型通过记忆工具记录稳定信息后会显示在这里。</p>
                        </div>
                    ) : (
                        <AnimatedList className="desktop-sections">
                            {visible.map((member) => (
                                <section
                                    className="ui-card memory-member"
                                    key={markerValue + member.userId}
                                >
                                    <div className="console-panel-heading">
                                        <div>
                                            <h3>{member.target || '聊天成员'}</h3>
                                            <p>QQ 号：{member.userId}</p>
                                        </div>
                                        {group && (
                                            <button
                                                className="btn"
                                                disabled={busy}
                                                onClick={() => void remove(false, member)}
                                            >
                                                <Trash2 size={15} />
                                                删除该成员记忆
                                            </button>
                                        )}
                                    </div>
                                    <div className="bot-form-grid">
                                        <label className="form-wide">
                                            长期印象（每行一条，单条最多 120 字）
                                            <textarea
                                                rows={4}
                                                disabled={busy}
                                                value={
                                                    drafts[member.userId] ??
                                                    member.entries.map((e) => e.content).join('\n')
                                                }
                                                onChange={(e) => {
                                                    dirty.current = true;
                                                    setDrafts((v) => ({
                                                        ...v,
                                                        [member.userId]: e.target.value,
                                                    }));
                                                }}
                                            />
                                        </label>
                                    </div>
                                    <div className="memory-save">
                                        <button
                                            className="btn btn-primary"
                                            disabled={busy}
                                            onClick={() => void save(member)}
                                        >
                                            <Save size={15} />
                                            保存
                                        </button>
                                    </div>
                                    {account && selected && (
                                        <MemoryReview
                                            account={account}
                                            chatKey={selected}
                                            member={member}
                                            disabled={busy || hasDrafts}
                                            onApplied={() => {
                                                setNotice('整理结果已应用；自动回复已暂停。');
                                                setMembers([]);
                                                refresh((v) => v + 1);
                                            }}
                                        />
                                    )}
                                </section>
                            ))}
                        </AnimatedList>
                    )}
                </RecordBrowser>
            )}
        </div>
    );
}
