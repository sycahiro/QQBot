import {
    RecordToolbar,
    RecordBrowser,
    RecordCard,
    RecordHeading,
    RecordEmpty,
} from '../components/record-browser';
import { useConfirm } from '../components/confirmation';
import { useEffect, useRef, useState } from 'react';
import { MessageSquare, Square, RotateCcw } from 'lucide-react';
import { Notice } from '../components/notice';
import { chatLabel, type Session } from '../business';

import { SessionDetail } from './session-detail';
import { statusNames } from './session-view';

export { statusNames } from './session-view';

export function useSessions(ready: boolean, revision = 0, limit = 200) {
    const [data, setData] = useState<{ account: string | null; items: Session[] }>({
        account: null,
        items: [],
    });
    const [error, setError] = useState('');
    useEffect(() => {
        if (!ready) return;
        let active = true;
        let timer: number;
        const read = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const result = await window.pywebview!.api.get_sessions(limit);
                    if (active && result.ok) {
                        setData(result);
                        setError('');
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('会话记录读取失败');
                }
            }
            if (active) timer = window.setTimeout(read, 2000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, revision, limit]);
    return { ...data, error };
}

export function Sessions({ ready }: { ready: boolean }) {
    const confirm = useConfirm();
    const [revision, refresh] = useState(0);
    const [limit, setLimit] = useState(200);
    const { account, items, error: readError } = useSessions(ready, revision, limit);
    const [chosen, choose] = useState<string | null>(null);
    const selected = items.some((item) => item.id === chosen) ? chosen : items[0]?.id;
    const current = items.find((item) => item.id === selected);
    const [detail, setDetail] = useState<Session | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const marker = useRef('');
    const mounted = useRef(true),
        working = useRef(false);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    marker.current = `${account}|${selected}`;
    useEffect(() => {
        if (!ready || !selected || !account) return;
        let active = true;
        let timer: number;
        const selectedMarker = `${account}|${selected}`;
        const read = async () => {
            if (!active) return;
            if (!document.hidden) {
                try {
                    const result = await window.pywebview!.api.get_session(selected);
                    if (
                        active &&
                        marker.current === selectedMarker &&
                        result.ok &&
                        result.account === account
                    ) {
                        setDetail(result.session);
                        setError('');
                        if (result.session?.status !== 'running') return;
                    } else if (active && !result.ok) setError(result.error.message);
                } catch {
                    if (active) setError('会话详情读取失败');
                }
            }
            if (active) timer = window.setTimeout(read, 2000);
        };
        void read();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [ready, selected, account, revision]);
    const remove = async (all: boolean) => {
        if (!account || working.current || (!all && !selected)) return;
        const expected = marker.current;
        if (
            !(await confirm(
                all
                    ? `确定清空当前账号的全部已结束会话日志？正在处理的会话会保留。`
                    : '确定删除当前会话日志？此操作不会删除聊天存档和记忆。',
                {
                    title: all ? '清空会话日志' : '删除会话日志',
                    confirmLabel: all ? '清空全部' : '删除',
                    danger: true,
                },
            ))
        )
            return;
        if (!mounted.current || marker.current !== expected || working.current) return;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = await window.pywebview!.api.delete_session(
                all ? null : selected!,
                account,
            );
            if (!mounted.current || marker.current !== expected) return;
            if (result.ok) {
                setNotice(`已删除 ${result.deleted} 条会话日志`);
                setDetail(null);
                choose(null);
                refresh((v) => v + 1);
            } else setError(result.error.message);
        } catch {
            if (mounted.current && marker.current === expected)
                setError('删除结果未确认，请刷新检查');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    const visible = detail && detail.id === selected && detail.account === account ? detail : null;
    const control = async (stop: boolean) => {
        if (!account || !selected || working.current) return;
        const expected = marker.current;
        if (
            !stop &&
            !(await confirm(
                '重新处理原会话的消息？会新建会话，可能再次调用模型和发送消息。原记录和实际发送结果会保留。',
                { title: '手动重跑', confirmLabel: '重新处理' },
            ))
        )
            return;
        if (!mounted.current || marker.current !== expected || working.current) return;
        working.current = true;
        setBusy(true);
        setError('');
        setNotice('');
        try {
            const result = stop
                ? await window.pywebview!.api.stop_session(selected, account)
                : await window.pywebview!.api.rerun_session(selected, account);
            if (!mounted.current || expected !== marker.current) return;
            if (result.ok) {
                setNotice(stop ? '正在停止当前会话，已发送的消息无法撤回。' : '已开始重新处理。');
                refresh((v) => v + 1);
            } else setError(result.error.message);
        } catch {
            if (mounted.current && expected === marker.current)
                setError('操作结果未确认，请刷新会话检查');
        } finally {
            working.current = false;
            if (mounted.current) setBusy(false);
        }
    };
    return (
        <div className="desktop-sections">
            <RecordToolbar
                summary={`处理记录 · ${items.length} 条`}
                noun="记录"
                remove={{
                    disabled: busy || !selected || current?.status === 'running',
                    run: () => void remove(false),
                }}
                clear={{ disabled: busy || !items.length, run: () => void remove(true) }}
                refresh={{ disabled: busy, run: () => refresh((v) => v + 1) }}
            />
            <Notice title="会话操作" message={error} error onClose={() => setError('')} />
            <Notice title="会话读取" message={readError} error onClose={() => {}} />
            <Notice title="会话操作" message={notice} onClose={() => setNotice('')} />
            {!items.length ? (
                <RecordEmpty icon={<MessageSquare size={28} />} title="还没有模型会话">
                    <p>连接机器人并处理消息后，新的处理记录会显示在这里。</p>
                </RecordEmpty>
            ) : (
                <RecordBrowser
                    identity={`${account}|${selected}`}
                    list={[
                        items.map((item) => (
                            <RecordCard
                                key={item.id}
                                selected={selected === item.id}
                                onSelect={() => choose(item.id)}
                                title={chatLabel(item).title}
                                subtitle={chatLabel(item).number}
                                preview={item.triggerText
                                    .split('\n')
                                    .filter((line) => line.trim())
                                    .at(-1)}
                                meta={new Date(item.started).toLocaleString('zh-CN', {
                                    hour12: false,
                                })}
                                badge={
                                    <span className={'session-status ' + item.status}>
                                        {item.status === 'error' && item.sent.length
                                            ? '已发送 · 异常'
                                            : statusNames[item.status]}
                                    </span>
                                }
                            />
                        )),
                        items.length >= limit && limit < 2000 && (
                            <button
                                key="older"
                                className="qq-refresh"
                                onClick={() => setLimit((value) => value + 200)}
                            >
                                加载更早会话
                            </button>
                        ),
                    ]}
                >
                    <RecordHeading
                        title={current ? chatLabel(current).title : '响应详情'}
                        subtitle={current ? chatLabel(current).number : ''}
                        actions={
                            <button
                                className="qq-refresh"
                                disabled={busy || !selected}
                                onClick={() => void control(current?.status === 'running')}
                            >
                                {current?.status === 'running' ? (
                                    <Square size={14} />
                                ) : (
                                    <RotateCcw size={14} />
                                )}
                                {current?.status === 'running' ? '停止' : '重新处理'}
                            </button>
                        }
                    />
                    {visible ? (
                        <SessionDetail key={visible.id} session={visible} />
                    ) : (
                        <p className="action-notice">正在读取响应详情…</p>
                    )}
                </RecordBrowser>
            )}
        </div>
    );
}
