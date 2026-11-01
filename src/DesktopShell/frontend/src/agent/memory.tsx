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
import { Brain, ChevronDown, RefreshCw, Save, Trash2, UserPlus, X } from 'lucide-react';
import { chatLabel, type MemoryChat, type MemoryMember } from '../business';
import { MemoryReview } from './memory-review';
import { Notice } from '../components/notice';
import { Collapse } from '../components/presence';

interface RosterMember {
    id: string;
    name: string;
}

// 中文名按拼音、英文按字母混排；与后端的号码排序解耦，列表位置只由名字决定。
const nameCollator = new Intl.Collator('zh-Hans-CN', { numeric: true });

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
    const [creating, setCreating] = useState(false);
    const [picked, pickMember] = useState<RosterMember | null>(null);
    const [createDraft, setCreateDraft] = useState('');
    const [roster, setRoster] = useState<RosterMember[] | null>(null);
    const [rosterQuery, setRosterQuery] = useState('');
    const [rosterBusy, setRosterBusy] = useState(false);
    const [rosterNonce, bumpRoster] = useState(0);
    const [expanded, setExpanded] = useState<string | null>(null);
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
        setCreating(false);
        pickMember(null);
        setCreateDraft('');
        setRoster(null);
        setRosterQuery('');
        setExpanded(null);
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
    const save = async (member: MemoryMember, textOverride?: string) => {
        if (!account || !selected || working.current || detailKey !== marker.current) return false;
        const expected = marker.current;
        const current = () => mounted.current && marker.current === expected;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const text =
                textOverride ??
                drafts[member.userId] ??
                member.entries.map((e) => e.content).join('\n');
            const result = await window.pywebview!.api.save_memory(
                selected,
                member.userId,
                member.target,
                text.split('\n').filter((v) => v.trim()),
                account,
            );
            if (!current()) return false;
            if (result.ok && result.account === account) {
                const latest = await window.pywebview!.api.get_memories(selected);
                if (!current()) return false;
                if (latest.ok && latest.account === account) setMembers(latest.members);
                setNotice('成员记忆已保存；如需继续处理新消息，请重新开启自动回复。');
                setDrafts((values) => {
                    const next = { ...values };
                    delete next[member.userId];
                    return next;
                });
                refresh((v) => v + 1);
                return true;
            }
            setError(result.ok ? '连接账号已变化，请重新打开记忆' : result.error.message);
            return false;
        } catch {
            if (current()) setError('保存结果未确认，请刷新检查');
            return false;
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
    const sortedMembers = [...visible].sort(
        (a, b) =>
            nameCollator.compare(a.target || a.userId, b.target || b.userId) ||
            nameCollator.compare(a.userId, b.userId),
    );
    const sortedRoster = roster
        ? [...roster].sort(
              (a, b) => nameCollator.compare(a.name, b.name) || nameCollator.compare(a.id, b.id),
          )
        : roster;
    const rosterMatches = sortedRoster
        ? sortedRoster.filter((m) =>
              `${m.name} ${m.id}`.toLowerCase().includes(rosterQuery.trim().toLowerCase()),
          )
        : [];
    const group = selected?.startsWith('group:');
    const peerId = selected?.startsWith('private:') ? selected.split(':')[1] : '';
    useEffect(() => {
        if (!creating || !group || !selected || !account || roster) return;
        let active = true;
        setRosterBusy(true);
        window
            .pywebview!.api.get_group_members(selected.split(':')[1], account)
            .then((result) => {
                if (!active) return;
                if (result.ok && result.account === account) setRoster(result.items);
                else setError(result.ok ? '连接账号已变化，请重新打开记忆' : result.error.message);
            })
            .catch(() => {
                if (active) setError('群成员列表读取失败，请点击重新读取重试');
            })
            .finally(() => {
                if (active) setRosterBusy(false);
            });
        return () => {
            active = false;
        };
        // rosterBusy 不进依赖：它的变化只是本 effect 自己的产物，进去会造成
        // 「cleanup 置废 active → 新一轮被守卫挡住 → 回调全部跳过」的死锁。
    }, [creating, group, selected, account, roster, rosterNonce]);
    const prefilled = (userId: string) =>
        members
            .find((m) => m.userId === userId)
            ?.entries.map((e) => e.content)
            .join('\n') ?? '';
    const startCreate = () => {
        setError('');
        setCreating(true);
        if (group) {
            pickMember(null);
            setCreateDraft('');
        } else {
            pickMember({ id: peerId, name: current?.name || peerId });
            setCreateDraft(prefilled(peerId));
        }
    };
    const choosePicked = (member: RosterMember) => {
        pickMember(member);
        setCreateDraft(prefilled(member.id));
    };
    const cancelCreate = () => {
        setCreating(false);
        pickMember(null);
        setCreateDraft('');
        dirty.current = false;
    };
    const saveCreate = async () => {
        if (!picked || !account || !selected) return;
        const lines = createDraft.split('\n').filter((v) => v.trim());
        if (!lines.length) {
            setError('请至少填写一条记忆内容，每行一条');
            return;
        }
        if (detailKey !== marker.current) {
            setError('成员列表尚未加载完成，请稍候再试');
            return;
        }
        const existing = members.find((m) => m.userId === picked.id);
        const ok = await save(
            { userId: picked.id, target: picked.name, entries: existing?.entries ?? [] },
            createDraft,
        );
        if (ok) {
            setCreating(false);
            pickMember(null);
            setCreateDraft('');
            dirty.current = false;
        }
    };
    return (
        <div className="desktop-sections">
            <RecordToolbar
                summary="查看、新建和编辑成员的长期记忆，每行一条。"
                noun="记忆"
                removeLabel="删除当前聊天记忆"
                remove={{ disabled: busy || !current?.count, run: () => void remove(false) }}
                clear={{
                    disabled: busy || !chats.some((c) => c.count),
                    run: () => void remove(true),
                }}
                refresh={{
                    disabled: busy || hasDrafts,
                    loading: busy,
                    run: () => refresh((v) => v + 1),
                }}
            />
            <Notice title="记忆操作" message={error} error onClose={() => setError('')} />
            <Notice title="记忆操作" message={notice} onClose={() => setNotice('')} />
            {!chats.length ? (
                <RecordEmpty icon={<Brain size={28} />} title="还没有成员记忆">
                    <p>模型记录的长期印象会显示在这里；选择一个聊天后可以手动新建。</p>
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
                        actions={
                            <button
                                className="btn"
                                disabled={busy || !selected || creating}
                                onClick={startCreate}
                            >
                                <UserPlus size={15} />
                                新建记忆
                            </button>
                        }
                    />
                    {detailKey !== markerValue ? (
                        <div className="desktop-empty">
                            <h3>正在读取记忆…</h3>
                            <p>模型通过记忆工具记录稳定信息后会显示在这里。</p>
                        </div>
                    ) : !visible.length && !creating ? (
                        <div className="desktop-empty">
                            <h3>暂无长期印象</h3>
                            <p>模型记录或手动新建的成员记忆会显示在这里。</p>
                        </div>
                    ) : (
                        <AnimatedList className="desktop-sections" staged>
                            {creating && (
                                <section
                                    className="ui-card memory-member"
                                    key="create"
                                    aria-label="新建成员记忆"
                                >
                                    <div className="console-panel-heading">
                                        <div>
                                            <h3>
                                                {picked
                                                    ? picked.name || '聊天成员'
                                                    : group
                                                      ? '选择群成员'
                                                      : '新建私聊记忆'}
                                            </h3>
                                            <p>
                                                {picked
                                                    ? `QQ 号：${picked.id}`
                                                    : group
                                                      ? '从下方群成员列表中选择一位'
                                                      : `记录对象：${peerId}`}
                                            </p>
                                        </div>
                                        <button
                                            className="btn"
                                            disabled={busy}
                                            onClick={cancelCreate}
                                        >
                                            <X size={15} />
                                            取消
                                        </button>
                                    </div>
                                    {group && !picked && (
                                        <div className="form-wide">
                                            <div className="contact-picker-toolbar">
                                                <input
                                                    aria-label="搜索群成员"
                                                    placeholder="搜索群名片、昵称或号码"
                                                    value={rosterQuery}
                                                    onChange={(e) => setRosterQuery(e.target.value)}
                                                />
                                                <button
                                                    type="button"
                                                    className="btn"
                                                    disabled={rosterBusy}
                                                    onClick={() => {
                                                        setRoster(null);
                                                        setRosterQuery('');
                                                        bumpRoster((v) => v + 1);
                                                    }}
                                                >
                                                    <RefreshCw
                                                        size={15}
                                                        className={
                                                            rosterBusy ? 'qq-scanning' : undefined
                                                        }
                                                    />
                                                    {roster ? '刷新成员' : '重新读取'}
                                                </button>
                                            </div>
                                            {sortedRoster && (
                                                <div className="contact-picker-list">
                                                    {rosterMatches.slice(0, 200).map((m) => (
                                                        <button
                                                            type="button"
                                                            className="contact-picker-item"
                                                            key={m.id}
                                                            disabled={busy}
                                                            onClick={() => choosePicked(m)}
                                                        >
                                                            <span>
                                                                <strong>{m.name}</strong>
                                                                <small>{m.id}</small>
                                                            </span>
                                                        </button>
                                                    ))}
                                                    {!rosterMatches.length && (
                                                        <p className="action-notice">
                                                            没有匹配成员
                                                        </p>
                                                    )}
                                                    {sortedRoster.length > 200 && (
                                                        <small>
                                                            共 {sortedRoster.length}
                                                            位成员，请用搜索缩小范围。
                                                        </small>
                                                    )}
                                                </div>
                                            )}
                                            {rosterBusy && (
                                                <p className="action-notice">正在读取群成员…</p>
                                            )}
                                        </div>
                                    )}
                                    {picked && (
                                        <>
                                            {members.some((m) => m.userId === picked.id) && (
                                                <p className="action-notice">
                                                    该成员已有记忆，保存将整体替换原有内容。
                                                </p>
                                            )}
                                            <div className="bot-form-grid">
                                                <label className="form-wide">
                                                    长期印象（每行一条，单条最多 120 字）
                                                    <textarea
                                                        rows={4}
                                                        disabled={busy}
                                                        value={createDraft}
                                                        onChange={(e) => {
                                                            dirty.current = true;
                                                            setCreateDraft(e.target.value);
                                                        }}
                                                    />
                                                </label>
                                            </div>
                                            <div className="memory-save">
                                                <button
                                                    className="btn btn-primary"
                                                    disabled={busy}
                                                    onClick={() => void saveCreate()}
                                                >
                                                    <Save size={15} />
                                                    保存记忆
                                                </button>
                                            </div>
                                        </>
                                    )}
                                </section>
                            )}
                            {sortedMembers.map((member) => {
                                const open = expanded === member.userId;
                                return (
                                    <section
                                        className="ui-card memory-member"
                                        key={markerValue + member.userId}
                                    >
                                        <button
                                            type="button"
                                            className="memory-member-toggle"
                                            aria-expanded={open}
                                            disabled={busy}
                                            onClick={() => setExpanded(open ? null : member.userId)}
                                        >
                                            <span
                                                className={
                                                    'disclosure-chevron' + (open ? ' is-open' : '')
                                                }
                                            >
                                                <ChevronDown size={15} />
                                            </span>
                                            <span className="memory-member-id">
                                                <strong>{member.target || '聊天成员'}</strong>
                                                <small>
                                                    QQ 号：{member.userId} · {member.entries.length}{' '}
                                                    条记忆
                                                </small>
                                            </span>
                                        </button>
                                        <Collapse open={open}>
                                            <div className="memory-member-body">
                                                <div className="memory-member-tools">
                                                    {group && (
                                                        <button
                                                            className="btn"
                                                            disabled={busy}
                                                            onClick={() =>
                                                                void remove(false, member)
                                                            }
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
                                                                member.entries
                                                                    .map((e) => e.content)
                                                                    .join('\n')
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
                                                            setNotice(
                                                                '整理结果已应用；自动回复已暂停。',
                                                            );
                                                            setMembers([]);
                                                            refresh((v) => v + 1);
                                                        }}
                                                    />
                                                )}
                                            </div>
                                        </Collapse>
                                    </section>
                                );
                            })}
                        </AnimatedList>
                    )}
                </RecordBrowser>
            )}
        </div>
    );
}
