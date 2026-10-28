import { uiTransition } from './motion';
import { useConfirm } from './components/confirmation';
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
    BookOpen,
    Bug,
    FlaskConical,
    MessageSquarePlus,
    RadioTower,
    Play,
    Search,
} from 'lucide-react';
import type { DebugAction, DebugEvent, QqConnectionInfo, Contact } from './desktop';
import { Select } from './components/select';
import { AnimatedList } from './components/animated-list';
import { ConnectionBoundary } from './components/connection-boundary';
import { Disclosure } from './components/disclosure';
import { Notice } from './components/notice';
import { DebugParameters } from './debug/parameters';
import { MessageBuilder } from './debug/message-builder';
import { buildMessage, newSegment, type Segment } from './debug/builder';
import { useTabNavigation } from './components/tab-navigation';

const tabs = [
    ['tester', '测试台', FlaskConical],
    ['compose', '消息构建', MessageSquarePlus],
    ['activity', '实时活动', RadioTower],
    ['api', 'API 浏览器', BookOpen],
] as const;
export function DebugTools({
    ready,
    connection,
}: {
    ready: boolean;
    connection?: QqConnectionInfo | null;
}) {
    return (
        <ConnectionBoundary
            ready={ready}
            connection={connection}
            icon={<Bug size={28} />}
            description="连接 QQ 后使用调试工具。"
        >
            {(account) => <ConnectedTools account={account.uin} />}
        </ConnectionBoundary>
    );
}
function ConnectedTools({ account }: { account: string }) {
    const confirm = useConfirm();
    const { tab, setTab, panel, minHeight, onExitComplete } =
        useTabNavigation<(typeof tabs)[number][0]>('tester');
    const [docs, setDocs] = useState<DebugAction[]>([]),
        [events, setEvents] = useState<DebugEvent[]>([]);
    const [action, setAction] = useState('get_login_info'),
        [params, setParams] = useState('{}');
    const [query, setQuery] = useState(''),
        [category, setCategory] = useState('');
    const [kind, setKind] = useState('private'),
        [peer, setPeer] = useState(''),
        [segments, setSegments] = useState<Segment[]>(() => [newSegment()]),
        [forward, setForward] = useState(false);
    const [contacts, setContacts] = useState<{ groups: Contact[]; private: Contact[] }>({
            groups: [],
            private: [],
        }),
        [loadingContacts, setLoadingContacts] = useState(false);
    const attachments = useRef(segments);
    attachments.current = segments;
    const [result, setResult] = useState<{ action: string; value: unknown } | null>(null);
    const [error, setError] = useState(''),
        [loadError, setLoadError] = useState(''),
        [busy, setBusy] = useState(false);
    const mounted = useRef(true),
        working = useRef(false),
        cursor = useRef(0);
    const reduced = useReducedMotion();
    useEffect(() => {
        mounted.current = true;
        void window
            .pywebview!.api.get_debug_catalog(account)
            .then((r) => {
                if (!mounted.current) return;
                if (r.ok && r.account === account) setDocs(r.actions);
                else if (!r.ok) setLoadError(r.error.message);
            })
            .catch(() => {
                if (mounted.current) setLoadError('接口文档读取失败，请重新打开调试页');
            });
        let timer: number;
        const poll = async () => {
            if (!mounted.current) return;
            if (!document.hidden)
                try {
                    const r = await window.pywebview!.api.get_debug_activity(
                        account,
                        cursor.current,
                    );
                    if (mounted.current && r.ok && r.account === account) {
                        cursor.current = r.cursor;
                        setEvents((old) => [...old, ...r.items].slice(-200));
                    }
                } catch {
                    /* The connected account boundary is supervised by the shell. */
                }
            if (mounted.current) timer = window.setTimeout(poll, 1000);
        };
        void poll();
        return () => {
            mounted.current = false;
            clearTimeout(timer);
            for (const s of attachments.current)
                if (s.attachment)
                    void window.pywebview!.api.discard_debug_file(s.attachment.token, account);
        };
    }, [account]);
    const choose = (name: string) => {
        setAction(name);
        setError('');
        const doc = docs.find((d) => d.name === name);
        const schema = doc?.inputSchema as
            | {
                  required?: string[];
                  properties?: Record<string, { default?: unknown; type?: string }>;
              }
            | undefined;
        setParams(
            JSON.stringify(
                Object.fromEntries(
                    (
                        schema?.required ||
                        (doc?.params || []).filter((p) => p.required).map((p) => p.name)
                    ).map((name) => [name, schema?.properties?.[name]?.default ?? '']),
                ),
                null,
                2,
            ),
        );
    };
    const run = async (name: string, values: unknown) => {
        if (working.current) return;
        if (
            name.startsWith('send_') &&
            !(await confirm(
                `将向选定目标发送以下调试消息：\n${JSON.stringify(values, null, 2)}\n确认发送？`,
                { title: '发送调试消息', confirmLabel: '发送' },
            ))
        )
            return;
        working.current = true;
        setBusy(true);
        setError('');
        setResult(null);
        try {
            const r = await window.pywebview!.api.run_debug_action(name, values, account);
            if (!mounted.current) return;
            if (r.ok && r.account === account) setResult({ action: name, value: r.result });
            else if (!r.ok) setError(r.error.message);
        } catch {
            if (mounted.current) setError('执行结果未确认，请检查 QQ 和实时活动，不会自动重试');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const selected = docs.find((d) => d.name === action);
    const available = docs.filter((d) => d.callable);
    const needsContacts = Boolean(
        selected &&
        JSON.stringify(selected.inputSchema || selected.params || []).match(
            /"(?:group_id|user_id|chat_key)"/,
        ),
    );
    const visible = docs.filter(
        (d) =>
            (!category || d.category === category) &&
            `${d.name} ${d.summary || ''}`.toLowerCase().includes(query.toLowerCase()),
    );
    const loadContacts = async () => {
        if (loadingContacts) return;
        setLoadingContacts(true);
        setError('');
        try {
            const r = await window.pywebview!.api.get_contacts(account);
            if (!mounted.current) return;
            if (r.ok && r.account === account)
                setContacts({ groups: r.groups, private: r.private });
            else if (!r.ok) setError(r.error.message);
        } catch {
            if (mounted.current) setError('联系人读取失败');
        } finally {
            if (mounted.current) setLoadingContacts(false);
        }
    };
    const message = buildMessage(segments, forward);
    const sendAction =
        kind === 'group'
            ? forward
                ? 'send_group_forward_msg'
                : 'send_group_msg'
            : forward
              ? 'send_private_forward_msg'
              : 'send_private_msg';
    return (
        <div className="desktop-sections">
            <nav className="agent-tabs" aria-label="调试工具">
                {tabs.map(([id, label, Icon]) => (
                    <button
                        key={id}
                        aria-current={tab === id ? 'page' : undefined}
                        onClick={() => setTab(id)}
                    >
                        <Icon size={16} />
                        {label}
                    </button>
                ))}
            </nav>
            {loadError && (
                <p className="desktop-error" role="alert">
                    {loadError}
                </p>
            )}
            <Notice title="调试操作" message={error} error onClose={() => setError('')} />
            <div ref={panel} style={{ minHeight }} className="tab-panel-frame">
                <AnimatePresence mode="wait" initial={false} onExitComplete={onExitComplete}>
                    <motion.div
                        key={tab}
                        className="desktop-sections"
                        initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: reduced ? 0 : -4 }}
                        transition={uiTransition(reduced)}
                    >
                        {tab === 'tester' && (
                            <section className="ui-card console-panel">
                                <div className="console-panel-heading">
                                    <div>
                                        <h2>接口测试台</h2>
                                        <p>手动检查 QQ 连接、联系人或消息接口；排查问题时使用。</p>
                                    </div>
                                    <FlaskConical size={18} />
                                </div>
                                <div className="bot-form-grid">
                                    <div className="bot-field">
                                        <span>接口</span>
                                        <Select
                                            label="调试接口"
                                            value={action}
                                            options={available.map((d) => ({
                                                value: d.name,
                                                label: `${d.summary || d.name} · ${d.name}`,
                                            }))}
                                            onChange={choose}
                                        />
                                    </div>
                                    <div className="bot-field">
                                        <span>用途</span>
                                        <p className="action-notice">
                                            {selected?.description ||
                                                selected?.summary ||
                                                selected?.returns ||
                                                '正在载入接口文档…'}
                                        </p>
                                    </div>
                                </div>
                                {needsContacts && (
                                    <div className="debug-contact-actions">
                                        <button
                                            className="qq-refresh"
                                            disabled={loadingContacts}
                                            onClick={() => void loadContacts()}
                                        >
                                            {loadingContacts ? '正在读取…' : '载入好友与群聊'}
                                        </button>
                                        <small>填充目标选择列表。</small>
                                    </div>
                                )}
                                <DebugParameters
                                    doc={selected}
                                    value={params}
                                    onChange={setParams}
                                    contacts={contacts}
                                />
                                <Disclosure
                                    title="编辑 JSON 参数"
                                    className="session-record debug-parameters"
                                >
                                    <div className="bot-form-grid">
                                        <label className="form-wide">
                                            JSON 参数
                                            <textarea
                                                rows={7}
                                                spellCheck={false}
                                                value={params}
                                                onChange={(e) => setParams(e.target.value)}
                                            />
                                            <small>可直接编辑接口参数。</small>
                                        </label>
                                    </div>
                                </Disclosure>
                                <div className="card-save-footer">
                                    <button
                                        className="qq-refresh primary-button"
                                        disabled={busy || !selected?.callable}
                                        onClick={() => {
                                            try {
                                                const parsed = JSON.parse(params);
                                                if (
                                                    !parsed ||
                                                    Array.isArray(parsed) ||
                                                    typeof parsed !== 'object'
                                                )
                                                    throw Error();
                                                void run(action, parsed);
                                            } catch {
                                                setError('参数必须是有效的 JSON 对象');
                                            }
                                        }}
                                    >
                                        <Play size={14} />
                                        {busy ? '执行中…' : '执行接口'}
                                    </button>
                                </div>
                            </section>
                        )}
                        {tab === 'compose' && (
                            <section className="ui-card console-panel">
                                <div className="console-panel-heading">
                                    <div>
                                        <h2>消息构建</h2>
                                        <p>组合消息片段，向白名单内的好友或群聊发送测试消息。</p>
                                    </div>
                                    <MessageSquarePlus size={18} />
                                </div>
                                <div className="bot-form-grid">
                                    <div className="bot-field">
                                        <span>聊天类型</span>
                                        <Select
                                            label="聊天类型"
                                            value={kind}
                                            options={[
                                                { value: 'private', label: '私聊' },
                                                { value: 'group', label: '群聊' },
                                            ]}
                                            onChange={setKind}
                                        />
                                    </div>
                                    <div className="bot-field">
                                        <span>{kind === 'group' ? '群号' : '好友 QQ 号'}</span>
                                        <Select
                                            editable
                                            label="发送目标"
                                            value={peer}
                                            options={(kind === 'group'
                                                ? contacts.groups
                                                : contacts.private
                                            ).map((c) => ({
                                                value: c.id,
                                                label: `${c.name} · ${c.id}`,
                                            }))}
                                            placeholder="输入号码，或读取联系人后选择"
                                            onChange={setPeer}
                                        />
                                    </div>
                                    <div className="bot-field">
                                        <span>发送方式</span>
                                        <Select
                                            label="发送方式"
                                            value={forward ? 'forward' : 'message'}
                                            options={[
                                                { value: 'message', label: '普通消息' },
                                                { value: 'forward', label: '合并转发' },
                                            ]}
                                            onChange={(v) => {
                                                if (
                                                    v === 'forward' &&
                                                    (segments.length > 5 ||
                                                        segments.some(
                                                            (s) =>
                                                                !['text', 'image', 'face'].includes(
                                                                    s.type,
                                                                ),
                                                        ))
                                                ) {
                                                    setError(
                                                        '合并转发最多5个节点，仅支持文字、图片和表情，请先调整片段。',
                                                    );
                                                    return;
                                                }
                                                setForward(v === 'forward');
                                            }}
                                        />
                                    </div>
                                    <div className="debug-contact-actions debug-compose-contacts">
                                        <button
                                            className="qq-refresh"
                                            disabled={loadingContacts}
                                            onClick={() => void loadContacts()}
                                        >
                                            {loadingContacts ? '正在读取…' : '读取 QQ 联系人'}
                                        </button>
                                        <small>填充目标选择列表。</small>
                                    </div>
                                </div>
                                <MessageBuilder
                                    account={account}
                                    segments={segments}
                                    onChange={setSegments}
                                    forward={forward}
                                    busy={busy}
                                    onError={setError}
                                />
                                <Disclosure
                                    className="session-record debug-json"
                                    title="查看生成的消息参数"
                                >
                                    <pre>
                                        {JSON.stringify(
                                            {
                                                [kind === 'group' ? 'group_id' : 'user_id']: peer,
                                                message,
                                            },
                                            null,
                                            2,
                                        )}
                                    </pre>
                                </Disclosure>
                                <div className="card-save-footer">
                                    <button
                                        className="qq-refresh primary-button"
                                        disabled={busy || !/^[1-9]\d{0,19}$/.test(peer)}
                                        onClick={() =>
                                            void run(sendAction, {
                                                [kind === 'group' ? 'group_id' : 'user_id']: peer,
                                                message,
                                            })
                                        }
                                    >
                                        <Play size={14} />
                                        确认并发送
                                    </button>
                                </div>
                            </section>
                        )}
                        {tab === 'activity' && (
                            <section className="ui-card console-panel">
                                <div className="console-panel-heading">
                                    <div>
                                        <h2>实时活动</h2>
                                        <p>查看当前账号的连接、消息和调试记录。</p>
                                    </div>
                                    <RadioTower size={18} />
                                </div>
                                <AnimatedList className="desktop-sections">
                                    {[...events].reverse().map((e) => (
                                        <article key={e.id} className="session-record">
                                            <small>
                                                {new Date(e.time).toLocaleTimeString('zh-CN', {
                                                    hour12: false,
                                                })}{' '}
                                                · {e.kind}
                                            </small>
                                            <p>{e.summary}</p>
                                            {e.detail !== undefined && (
                                                <Disclosure title="参数、耗时与结果">
                                                    <pre>{JSON.stringify(e.detail, null, 2)}</pre>
                                                </Disclosure>
                                            )}
                                        </article>
                                    ))}
                                </AnimatedList>
                                {!events.length && (
                                    <p className="action-notice">
                                        还没有活动。新收到的白名单消息或接口执行会显示在这里。
                                    </p>
                                )}
                            </section>
                        )}
                        {tab === 'api' && (
                            <section className="ui-card console-panel">
                                <div className="console-panel-heading">
                                    <div>
                                        <h2>API 文档 · {docs.length} 项</h2>
                                        <p>
                                            原项目的接口参考；{available.length}{' '}
                                            项可手动测试，其余仅供查阅。机器人按需调用已接入的功能。
                                        </p>
                                    </div>
                                    <BookOpen size={18} />
                                </div>
                                <div className="bot-form-grid">
                                    <label>
                                        搜索接口
                                        <input
                                            value={query}
                                            onChange={(e) => setQuery(e.target.value)}
                                            placeholder="名称或说明…"
                                        />
                                    </label>
                                    <div className="bot-field">
                                        <span>分类</span>
                                        <Select
                                            label="接口分类"
                                            value={category}
                                            options={[
                                                { value: '', label: '全部分类' },
                                                ...[
                                                    ...new Set(
                                                        docs.map((d) => d.category || '其他'),
                                                    ),
                                                ].map((c) => ({ value: c, label: c })),
                                            ]}
                                            onChange={setCategory}
                                        />
                                    </div>
                                </div>
                                <div className="debug-api-list">
                                    {visible.map((d) => (
                                        <article key={d.name} className="session-record">
                                            <div className="tool-heading">
                                                <strong>{d.name}</strong>
                                                <small>
                                                    {d.category} ·{' '}
                                                    {d.readOnly ? '查询' : '有副作用'}
                                                </small>
                                            </div>
                                            <p>
                                                {d.description ||
                                                    d.summary ||
                                                    d.returns ||
                                                    '暂无说明'}
                                            </p>
                                            <Disclosure title="参数与返回说明">
                                                <pre>
                                                    {JSON.stringify(
                                                        d.inputSchema || d.params || {},
                                                        null,
                                                        2,
                                                    )}
                                                </pre>
                                                <p>{d.returns}</p>
                                            </Disclosure>
                                            {d.callable ? (
                                                <button
                                                    className="qq-refresh"
                                                    onClick={() => {
                                                        choose(d.name);
                                                        setTab('tester');
                                                    }}
                                                >
                                                    <Search size={13} />
                                                    试一下
                                                </button>
                                            ) : (
                                                <small className="action-notice">
                                                    仅提供文档。
                                                </small>
                                            )}
                                        </article>
                                    ))}
                                </div>
                            </section>
                        )}
                    </motion.div>
                </AnimatePresence>
            </div>
            <AnimatePresence initial={false}>
                {result && (
                    <motion.section
                        className="ui-card console-panel debug-result-card"
                        key={result.action}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={uiTransition(reduced)}
                    >
                        <h2>{result.action} · 执行结果</h2>
                        <pre className="debug-result">{JSON.stringify(result.value, null, 2)}</pre>
                    </motion.section>
                )}
            </AnimatePresence>
        </div>
    );
}
