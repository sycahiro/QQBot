import {
    RecordToolbar,
    RecordBrowser,
    RecordCard,
    RecordHeading,
    RecordEmpty,
} from '../components/record-browser';
import { ArchiveMessages } from './archive-messages';
import { useConfirm } from '../components/confirmation';
import { useEffect, useRef, useState } from 'react';

import { MessageSquare, Search, X, Play, CheckCheck, ListFilter } from 'lucide-react';
import { Notice } from '../components/notice';
import { chatLabel, type ArchivedMessage, type ChatSummary } from '../business';

export function Archive({ ready }: { ready: boolean }) {
    const confirm = useConfirm();
    const [account, setAccount] = useState<string | null>(null);
    const [chats, setChats] = useState<ChatSummary[]>([]);
    const [selected, setSelected] = useState<string | null>(null);
    const [items, setItems] = useState<ArchivedMessage[]>([]);
    const [itemsKey, setItemsKey] = useState('');
    const [before, setBefore] = useState<number | null>(null);
    const [history, setHistory] = useState(false);
    const [busy, setBusy] = useState(false);
    const [loadingOlder, setLoadingOlder] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [collectNotice, setCollectNotice] = useState('');
    const [revision, refresh] = useState(0);
    const [draftQuery, setDraftQuery] = useState('');
    const [query, setQuery] = useState('');
    const [totalMatches, setTotalMatches] = useState(0);
    const [unreadOnly, setUnreadOnly] = useState(false);
    const [readState, setReadState] = useState({ unread: 0, unreadChats: 0, readThrough: 0 });
    const readWorking = useRef(false),
        listEpoch = useRef(0);
    const unreadFilter = useRef(unreadOnly);
    unreadFilter.current = unreadOnly;
    const accountRef = useRef<string | null>(null);
    const historyRef = useRef(false);
    const selectionRef = useRef('');
    const selectedRef = useRef<string | null>(null);
    const olderRequest = useRef(0);
    const mounted = useRef(true);
    selectionRef.current = JSON.stringify([account, selected, query]);
    selectedRef.current = selected;
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);

    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const update = async () => {
            if (!active) return;
            if (!document.hidden) {
                const epoch = listEpoch.current;
                try {
                    const result = await window.pywebview!.api.get_archives(unreadOnly);
                    if (
                        active &&
                        epoch === listEpoch.current &&
                        !readWorking.current &&
                        result.ok
                    ) {
                        const changed = accountRef.current !== result.account;
                        accountRef.current = result.account;
                        setAccount(result.account);
                        setChats(result.items);
                        setReadState({
                            unread: result.unread,
                            unreadChats: result.unreadChats,
                            readThrough: result.readThrough,
                        });
                        const candidates = unreadOnly
                            ? result.items.filter((item) => item.unread > 0)
                            : result.items;
                        const next =
                            !changed &&
                            candidates.some((item) => item.chatKey === selectedRef.current)
                                ? selectedRef.current
                                : (candidates[0]?.chatKey ?? null);
                        setSelected(next);
                        if (changed || next !== selectedRef.current) {
                            historyRef.current = false;
                            setHistory(false);
                            setItems([]);
                            setBefore(null);
                            setLoadingOlder(false);
                            ++olderRequest.current;
                        }
                        if (changed) {
                            setQuery('');
                            setDraftQuery('');
                        }
                    } else if (active && epoch === listEpoch.current && !result.ok)
                        setError(result.error.message);
                } catch {
                    if (active) setError('聊天存档读取失败，请刷新重试');
                }
            }
            if (active) timer = window.setTimeout(update, 2000);
        };
        void update();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, revision, unreadOnly]);

    useEffect(() => {
        if (!ready || !account || !selected || history) return;
        let active = true;
        let timer: number;
        const marker = JSON.stringify([account, selected, query]);
        const update = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const result = await window.pywebview!.api.get_archive_messages(
                        selected,
                        query,
                        null,
                        account,
                    );
                    if (
                        active &&
                        !historyRef.current &&
                        selectionRef.current === marker &&
                        result.ok &&
                        result.account === account
                    ) {
                        setItems(result.items);
                        setItemsKey(marker);
                        setBefore(result.nextBefore);
                        setTotalMatches(result.totalMatches);
                        setError('');
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('消息读取失败，请刷新重试');
                }
            }
            if (active) timer = window.setTimeout(update, 2000);
        };
        void update();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, account, selected, query, history, revision]);

    const older = async () => {
        if (
            !account ||
            !selected ||
            before == null ||
            busy ||
            loadingOlder ||
            itemsKey !== selectionRef.current
        )
            return;
        const marker = selectionRef.current;
        const request = ++olderRequest.current;
        historyRef.current = true;
        setHistory(true);
        setLoadingOlder(true);
        try {
            const result = await window.pywebview!.api.get_archive_messages(
                selected,
                query,
                before,
                account,
            );
            if (
                !mounted.current ||
                marker !== selectionRef.current ||
                request !== olderRequest.current
            )
                return;
            if (result.ok && result.account === account) {
                setItems((current) =>
                    [
                        ...new Map(
                            [...result.items, ...current].map((item) => [item.id, item]),
                        ).values(),
                    ].sort((a, b) => a.id - b.id),
                );
                setBefore(result.nextBefore);
                setTotalMatches(result.totalMatches);
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (
                mounted.current &&
                marker === selectionRef.current &&
                request === olderRequest.current
            )
                setError('较早消息读取失败');
        } finally {
            if (mounted.current && request === olderRequest.current) setLoadingOlder(false);
        }
    };

    const remove = async (all: boolean) => {
        if (!account || busy || loadingOlder || (!all && !selected)) return;
        const scope = all
            ? `当前账号的全部聊天存档`
            : current
              ? chatLabel(current).title + '的聊天存档'
              : '当前聊天存档';
        const expected = selectionRef.current;
        if (
            !(await confirm(
                `确定删除${scope}？${query && !all ? '将删除当前聊天的全部存档，包含搜索未显示的消息。' : ''}删除后无法恢复。`,
                {
                    title: all ? '清空聊天存档' : '删除聊天存档',
                    confirmLabel: all ? '清空全部' : '删除',
                    danger: true,
                },
            ))
        )
            return;
        if (!mounted.current || selectionRef.current !== expected) return;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.delete_archive(
                all ? null : selected!,
                account,
            );
            if (!mounted.current || selectionRef.current !== expected) return;
            if (result.ok) {
                setNotice(`已删除 ${result.deleted} 条存档消息`);
                setItems([]);
                setSelected(null);
                historyRef.current = false;
                setHistory(false);
                ++olderRequest.current;
                refresh((v) => v + 1);
            } else setError(result.error.message);
        } catch {
            if (mounted.current && selectionRef.current === expected)
                setError('删除未确认，请刷新检查');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    const current = chats.find((item) => item.chatKey === selected);
    const visibleChats = unreadOnly ? chats.filter((chat) => chat.unread > 0) : chats;
    useEffect(() => {
        if (unreadOnly && !visibleChats.some((chat) => chat.chatKey === selected)) {
            setSelected(visibleChats[0]?.chatKey ?? null);
            historyRef.current = false;
            setHistory(false);
            setBefore(null);
            setLoadingOlder(false);
            ++olderRequest.current;
        }
    }, [unreadOnly, chats, selected]);
    const markRead = async (all: boolean) => {
        if (!account || busy || loadingOlder || readWorking.current || (!all && !current)) return;
        const expected = account,
            through = all ? readState.readThrough : current!.lastId;
        readWorking.current = true;
        ++listEpoch.current;
        setBusy(true);
        setError('');
        setCollectNotice('');
        try {
            const result = await window.pywebview!.api.mark_archive_read(
                all ? null : current!.chatKey,
                through,
                expected,
            );
            if (!mounted.current || accountRef.current !== expected) return;
            if (!result.ok) {
                setError(result.error.message);
                return;
            }
            if (result.account !== expected) return;
            setCollectNotice(`已将 ${result.marked} 条消息标记已读。`);
            const filter = unreadFilter.current;
            const snapshot = await window.pywebview!.api.get_archives(filter);
            if (
                mounted.current &&
                accountRef.current === expected &&
                unreadFilter.current === filter &&
                snapshot.ok &&
                snapshot.account === expected
            ) {
                setChats(snapshot.items);
                setReadState({
                    unread: snapshot.unread,
                    unreadChats: snapshot.unreadChats,
                    readThrough: snapshot.readThrough,
                });
                setItems((values) =>
                    values.map((item) =>
                        all || selectedRef.current === current?.chatKey
                            ? { ...item, read: item.read || item.id <= through }
                            : item,
                    ),
                );
            }
        } catch {
            if (mounted.current && accountRef.current === expected)
                setError('已读状态未确认，请刷新检查');
        } finally {
            readWorking.current = false;
            ++listEpoch.current;
            if (mounted.current) {
                setBusy(false);
                refresh((v) => v + 1);
            }
        }
    };
    const collect = async (item: ArchivedMessage) => {
        if (!account || !selected || !item.mid || busy) return;
        const expected = selectionRef.current;
        setBusy(true);
        setError('');
        setCollectNotice('');
        try {
            const result = await window.pywebview!.api.collect_sticker(selected, item.mid, account);
            if (!mounted.current || expected !== selectionRef.current) return;
            if (result.ok && result.account === account)
                setCollectNotice(
                    result.item.duplicate ? '这张图片已在表情库中。' : '已收藏，可在表情库查看。',
                );
            else if (!result.ok) setError(result.error.message);
        } catch {
            if (mounted.current && expected === selectionRef.current)
                setError('收藏结果未确认，请到表情库检查');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    const label = current ? chatLabel(current) : null;
    const process = async () => {
        if (!account || !selected || busy) return;
        const expected = selectionRef.current;
        if (
            !(await confirm(
                '处理当前聊天最近一条可用的对方消息？将调用模型，并可能向当前聊天发送回复。不会开启自动回复。',
                { title: '处理一次', confirmLabel: '开始处理' },
            ))
        )
            return;
        if (!mounted.current || selectionRef.current !== expected) return;
        setBusy(true);
        setError('');
        setCollectNotice('');
        try {
            const result = await window.pywebview!.api.process_archive(selected, account);
            if (!mounted.current || expected !== selectionRef.current) return;
            if (result.ok) setCollectNotice('已开始处理，可在会话中查看结果。');
            else setError(result.error.message);
        } catch {
            if (mounted.current && expected === selectionRef.current)
                setError('处理提交结果未确认，请到会话检查，不要重复点击');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    const expand = async (item: ArchivedMessage) => {
        if (!account || !selected || !item.mid || busy) return;
        const expected = selectionRef.current;
        setBusy(true);
        setError('');
        setCollectNotice('');
        try {
            const result = await window.pywebview!.api.expand_forward(selected, item.mid, account);
            if (!mounted.current || expected !== selectionRef.current) return;
            if (result.ok && result.account === account) {
                setItems((values) =>
                    values.map((value) =>
                        value.id === item.id ? { ...value, text: result.text } : value,
                    ),
                );
                setCollectNotice(result.cached ? '已读取存档中的转发内容。' : '转发文字已展开。');
            } else if (!result.ok) setError(result.error.message);
        } catch {
            if (mounted.current && expected === selectionRef.current)
                setError('展开结果未确认，请刷新存档检查');
        } finally {
            if (mounted.current) setBusy(false);
        }
    };
    const visibleItems = itemsKey === selectionRef.current ? items : [];
    const search = (value: string) => {
        setQuery(value.trim());
        setBefore(null);
        setLoadingOlder(false);
        ++olderRequest.current;
        historyRef.current = false;
        setHistory(false);
        setError('');
        refresh((v) => v + 1);
    };
    return (
        <div className="desktop-sections">
            <Notice title="操作结果" message={collectNotice} onClose={() => setCollectNotice('')} />
            <RecordToolbar
                summary="查看已接入聊天的消息记录。"
                noun="存档"
                remove={{
                    disabled: busy || loadingOlder || !selected,
                    run: () => void remove(false),
                }}
                clear={{
                    disabled: busy || loadingOlder || chats.length === 0,
                    run: () => void remove(true),
                }}
                refresh={{
                    disabled: busy,
                    run: () => {
                        setError('');
                        refresh((v) => v + 1);
                    },
                }}
                actions={
                    <button
                        type="button"
                        className="qq-refresh"
                        disabled={busy || !selected}
                        onClick={() => void process()}
                    >
                        <Play size={14} />
                        处理一次
                    </button>
                }
            />
            <div className="archive-unread-toolbar">
                <div>
                    <strong>
                        {readState.unread} 条未读 · {readState.unreadChats} 个聊天
                    </strong>
                    <p>机器人尚未处理的消息，可手动标记已读。</p>
                </div>
                <div className="archive-read-actions">
                    <button
                        className="qq-refresh"
                        aria-pressed={unreadOnly}
                        onClick={() => setUnreadOnly((value) => !value)}
                    >
                        <ListFilter size={14} />
                        {unreadOnly ? '显示全部聊天' : '仅看未读'}
                    </button>
                    <button
                        className="qq-refresh"
                        disabled={busy || loadingOlder || !current?.unread}
                        onClick={() => void markRead(false)}
                    >
                        <CheckCheck size={14} />
                        当前聊天标记已读
                    </button>
                    <button
                        className="qq-refresh"
                        disabled={busy || loadingOlder || readState.unread === 0}
                        onClick={() => void markRead(true)}
                    >
                        <CheckCheck size={14} />
                        全部标记已读
                    </button>
                </div>
            </div>
            <Notice title="聊天存档" message={error} error onClose={() => setError('')} />
            <Notice title="聊天存档" message={notice} onClose={() => setNotice('')} />
            {visibleChats.length === 0 ? (
                <RecordEmpty
                    icon={<MessageSquare size={28} />}
                    title={
                        unreadOnly
                            ? '没有未读聊天'
                            : account
                              ? '还没有聊天存档'
                              : '请先选择机器人账号'
                    }
                >
                    <p>
                        {unreadOnly
                            ? '可以切回全部聊天查看已归档消息。'
                            : account
                              ? '连接机器人并配置聊天白名单后，新收到的消息会保存在这里。'
                              : '连接并选择要使用的机器人账号。'}
                    </p>
                </RecordEmpty>
            ) : (
                <RecordBrowser
                    identity={JSON.stringify([account, selected])}
                    detailClassName="archive-thread-panel"
                    list={[
                        visibleChats.map((chat) => {
                            const caption = chatLabel(chat);
                            return (
                                <RecordCard
                                    key={chat.chatKey}
                                    selected={selected === chat.chatKey}
                                    onSelect={() => {
                                        setSelected(chat.chatKey);
                                        historyRef.current = false;
                                        setHistory(false);
                                        setBefore(null);
                                        setLoadingOlder(false);
                                        ++olderRequest.current;
                                    }}
                                    title={caption.title}
                                    subtitle={caption.number}
                                    preview={
                                        <>
                                            {chat.lastSenderName}：{chat.lastText}
                                        </>
                                    }
                                    badge={
                                        chat.unread > 0 && (
                                            <span
                                                className="archive-unread-badge"
                                                aria-label={`${chat.unread}条未读`}
                                            >
                                                {chat.unread > 99 ? '99+' : chat.unread}
                                            </span>
                                        )
                                    }
                                />
                            );
                        }),
                    ]}
                >
                    <div className="archive-thread-header">
                        <RecordHeading
                            title={label?.title}
                            subtitle={label?.number}
                            icon={<MessageSquare size={18} />}
                        />
                        <form
                            className="archive-search"
                            role="search"
                            aria-label="搜索当前聊天存档"
                            onSubmit={(event) => {
                                event.preventDefault();
                                search(draftQuery);
                            }}
                        >
                            <label className="archive-search-input">
                                <Search size={16} />
                                <input
                                    aria-label="搜索消息、昵称或用户编号"
                                    maxLength={200}
                                    value={draftQuery}
                                    placeholder="搜索消息、昵称或用户编号"
                                    onChange={(event) => setDraftQuery(event.target.value)}
                                />
                            </label>
                            <button className="qq-refresh" type="submit">
                                搜索
                            </button>
                            {(query || draftQuery) && (
                                <button
                                    className="qq-refresh"
                                    type="button"
                                    onClick={() => {
                                        setDraftQuery('');
                                        search('');
                                    }}
                                >
                                    <X size={14} />
                                    清除
                                </button>
                            )}
                        </form>
                        {itemsKey === selectionRef.current && (
                            <p className="action-notice archive-search-summary">
                                {query
                                    ? `“${query}”匹配 ${totalMatches} 条消息`
                                    : `共 ${totalMatches} 条消息`}{' '}
                                · 已显示 {visibleItems.length} 条
                            </p>
                        )}
                        <div className="archive-history-actions">
                            {before != null && itemsKey === selectionRef.current && (
                                <button
                                    className="qq-refresh"
                                    disabled={busy || loadingOlder}
                                    onClick={() => void older()}
                                >
                                    {loadingOlder
                                        ? '加载中…'
                                        : `加载更早${query ? '结果' : '消息'}`}
                                </button>
                            )}
                            {history && (
                                <button
                                    className="qq-refresh"
                                    onClick={() => {
                                        ++olderRequest.current;
                                        historyRef.current = false;
                                        setHistory(false);
                                        setLoadingOlder(false);
                                    }}
                                >
                                    返回最新{query ? '结果' : ''}
                                </button>
                            )}
                        </div>
                    </div>
                    <ArchiveMessages
                        key={selectionRef.current}
                        items={visibleItems}
                        loaded={itemsKey === selectionRef.current}
                        query={query}
                        history={history}
                        busy={busy}
                        onExpand={(item) => void expand(item)}
                        onCollect={(item) => void collect(item)}
                    />
                </RecordBrowser>
            )}
        </div>
    );
}
