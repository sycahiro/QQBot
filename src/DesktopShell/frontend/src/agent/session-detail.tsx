import {
    Check,
    CircleAlert,
    Clock3,
    MessageSquare,
    LoaderCircle,
    Square,
    FileText,
    Brain,
    Bot,
    Layers,
    ReceiptText,
    Zap,
    type LucideIcon,
} from 'lucide-react';
import type { ReactNode } from 'react';
import type { Session, SessionRecord } from '../business';
import { Disclosure } from '../components/disclosure';
import { AnimatedList } from '../components/animated-list';
import { StatusSwap } from '../components/status-swap';
import { duration, requestCount, sessionOutcome } from './session-view';

const names: Record<string, string> = {
    send_message: '发送消息',
    send_image: '发送图片',
    finish: '结束处理',
    get_recent_messages: '读取聊天记录',
    get_message_images: '查看消息图片',
    memory_append: '保存记忆',
    memory_query: '查询记忆',
    memory_remove: '删除记忆',
    read_forward: '展开合并转发',
    get_message_detail: '读取消息详情',
    get_active_members: '查看活跃成员',
    web_search: '联网搜索',
    web_fetch: '阅读网页',
    collect_sticker: '收藏表情',
    list_stickers: '查询表情库',
    get_sticker_image: '查看表情',
    sticker_note: '备注表情',
    send_sticker: '发送表情',
    send_poke: '拍一拍',
};
const text = (value: unknown) => (typeof value === 'string' ? value : '');
export function toolOutcome(record: SessionRecord) {
    if (record.status === 'running') return '执行中';
    if (record.status === 'aborted') return '已停止';
    if (record.isError || record.status === 'error') return '执行失败';
    const result = record.result;
    if (result?.preview) return '已预览';
    if (Number(result?.sent) > 0) return `已发送 ${result?.sent} 条`;
    if (Number(result?.deduped) > 0) return '已跳过重复发送';
    if (record.name === 'send_poke') return result?.poked ? '已确认' : '未确认';
    if (record.name?.startsWith('send_')) return '未确认发送';
    return record.name === 'finish' ? '已结束' : '已完成';
}
function explanation(record: SessionRecord) {
    const result = record.result;
    if (record.status === 'running') return '';
    if (record.isError || record.status === 'aborted')
        return text(result?.error) || text(result?.message);
    if (Number(result?.deduped) > 0)
        return record.name === 'send_poke'
            ? '拍一拍仍在冷却期，本次未重复执行'
            : Number(result?.sent) > 0
              ? `本次新增 ${result?.sent} 条发送，另跳过 ${result?.deduped} 条本轮已发送的重复内容`
              : '本轮已确认发送过相同内容，此次调用没有新增发送';
    if (record.name === 'get_message_images')
        return `${result?.count ?? 0} 张图片${result?.understandingModel ? ` · ${result.understandingModel}` : ''}`;
    if (record.name === 'web_search' && Array.isArray(result?.results))
        return `${result.results.length} 条搜索结果`;
    if (record.name === 'get_recent_messages' && Array.isArray(result?.messages))
        return `${result.messages.length} 条消息`;
    if (record.name === 'get_active_members' && Array.isArray(result?.members))
        return `${result.members.length} 位成员`;
    if (record.name === 'list_stickers' && Array.isArray(result?.stickers))
        return `${result.stickers.length} 张表情`;
    if (record.name === 'send_image' || record.name === 'send_sticker')
        return result?.preview ? '图片预览完成，尚未发送' : '';
    if (record.name === 'finish' || record.name === 'send_message') return '';
    if (record.name === 'collect_sticker')
        return result?.duplicate ? '表情已在库中' : '已收藏到表情库';
    return text(result?.text).slice(0, 160) || text(result?.message);
}
function Step({ record, index }: { record: SessionRecord; index: number }) {
    const running = record.status === 'running',
        stopped = record.status === 'aborted';
    const failed = record.isError || record.status === 'error';
    const Icon = running ? LoaderCircle : stopped ? Square : failed ? CircleAlert : Check;
    const summary = explanation(record);
    return (
        <article
            className={`session-step${failed ? ' is-error' : ''}${running ? ' is-running' : ''}`}
        >
            <span className="session-step-index">{index + 1}</span>
            <div className="session-step-body">
                <div className="tool-heading">
                    <strong>{names[record.name || ''] || record.name || '执行工具'}</strong>
                    <small>
                        <Icon size={12} className={running ? 'session-spinner' : undefined} />
                        {toolOutcome(record)}
                        {duration(record) && <span> · {duration(record)}</span>}
                    </small>
                </div>
                {summary && <p>{summary}</p>}
                {!running && (
                    <Disclosure title="参数与结果" className="session-step-data">
                        <pre>
                            {JSON.stringify(
                                { parameters: record.args, result: record.result },
                                null,
                                2,
                            )}
                        </pre>
                    </Disclosure>
                )}
            </div>
        </article>
    );
}
function RecordCard({
    icon: Icon,
    title,
    summary,
    meta,
    children,
}: {
    icon: LucideIcon;
    title: string;
    summary: string;
    meta?: string;
    children: ReactNode;
}) {
    return (
        <Disclosure
            className="session-context-entry"
            title={
                <span className="session-record-heading">
                    <span className="session-record-icon">
                        <Icon size={17} />
                    </span>
                    <span className="session-record-copy">
                        <strong>{title}</strong>
                        <small>{summary}</small>
                    </span>
                    {meta && <span className="session-record-meta">{meta}</span>}
                </span>
            }
        >
            {children}
        </Disclosure>
    );
}
const preview = (value: string) => value.replace(/\s+/g, ' ').trim().slice(0, 100);
export function SessionDetail({ session }: { session: Session }) {
    const records = session.records ?? [];
    const tools = records.filter((r) => r.kind === 'tool');
    const context = records.filter(
        (r) =>
            ['prompt', 'reasoning', 'assistant', 'note'].includes(r.kind) &&
            (r.text || r.messages?.length),
    );
    const requests = records.filter((r) => r.kind === 'model_request');
    const seconds =
        session.ended === null ? null : Math.max(0, (session.ended - session.started) / 1000);
    const latest = requests.at(-1);
    const active = tools.find((r) => r.status === 'running');
    const state = active
        ? `${names[active.name || ''] || '工具'}执行中`
        : latest?.status === 'running'
          ? latest.stage === 'media'
              ? '正在识别媒体'
              : '正在等待模型'
          : '正在处理';
    return (
        <div className="session-inspector">
            <section
                className={
                    'session-outcome status-box' +
                    (session.status === 'running'
                        ? ' is-pending'
                        : session.status === 'done'
                          ? ' is-ready'
                          : session.status === 'error'
                            ? ' is-error'
                            : '')
                }
            >
                <div className="session-outcome-title">
                    <strong>
                        <span className="session-state-dot" />
                        <StatusSwap
                            text={session.status === 'running' ? state : sessionOutcome(session)}
                        />
                    </strong>
                    <time dateTime={new Date(session.started).toISOString()}>
                        {new Date(session.started).toLocaleString('zh-CN', { hour12: false })}
                    </time>
                </div>
                {session.reason && <p>{session.reason}</p>}
            </section>
            <dl className="session-facts">
                <div>
                    <dt>聊天模型</dt>
                    <dd>{session.model || '未请求'}</dd>
                </div>
                <div>
                    <dt>模型调用</dt>
                    <dd>{requestCount(session)} 次</dd>
                </div>
                <div>
                    <dt>Token</dt>
                    <dd>{session.usage.totalTokens.toLocaleString()}</dd>
                </div>
                <div>
                    <dt>耗时</dt>
                    <dd>{seconds === null ? '进行中' : `${seconds.toFixed(1)} 秒`}</dd>
                </div>
            </dl>
            <section className="session-reply">
                <h3>
                    <MessageSquare size={15} />
                    实际回复<span>{session.sent.length} 条回执</span>
                </h3>
                {session.sent.length ? (
                    <div className="session-deliveries">
                        {session.sent.map((sent, index) => (
                            <article key={index}>
                                <p>{sent.text || (sent.type === 'poke' ? '拍一拍' : '图片消息')}</p>
                                <small>
                                    {sent.verified === false ? (
                                        '历史记录 · 未核验'
                                    ) : (
                                        <>
                                            <Check size={12} />
                                            QQ 已确认
                                        </>
                                    )}
                                    <time>
                                        {new Date(sent.ts).toLocaleTimeString('zh-CN', {
                                            hour12: false,
                                        })}
                                    </time>
                                </small>
                            </article>
                        ))}
                    </div>
                ) : (
                    <p className="session-empty">
                        {session.status === 'running' ? '等待发送回执' : '没有已确认发送的回复'}
                    </p>
                )}
            </section>
            <section className="session-process">
                <h3>
                    <Clock3 size={15} />
                    执行过程<span>{tools.length} 步</span>
                </h3>
                <AnimatedList className="session-steps">
                    {tools.map((r, index) => (
                        <Step key={index} record={r} index={index} />
                    ))}
                </AnimatedList>
                {!tools.length && (
                    <p className="session-empty">
                        {session.status === 'running' ? '等待模型选择操作' : '未执行工具'}
                    </p>
                )}
            </section>
            <Disclosure
                title={
                    <span className="session-context-title">
                        <FileText size={16} />
                        <strong>详细记录</strong>
                        <small>输入与模型过程</small>
                    </span>
                }
                className="session-context"
            >
                <div className="session-context-grid">
                    {session.triggerText && (
                        <RecordCard
                            icon={MessageSquare}
                            title="触发消息"
                            summary={preview(session.triggerText)}
                        >
                            <p>{session.triggerText}</p>
                        </RecordCard>
                    )}
                    {requests.length > 0 && (
                        <RecordCard
                            icon={Zap}
                            title="模型调用"
                            meta={`${requests.length} 次`}
                            summary={[
                                ...new Set(requests.map((r) => r.model).filter(Boolean)),
                            ].join(' · ')}
                        >
                            <ol className="session-request-list">
                                {requests.map((r, index) => (
                                    <li key={index}>
                                        <strong>
                                            {r.stage === 'media' ? '媒体理解' : '聊天'} · {r.model}
                                        </strong>
                                        <small>
                                            {r.protocol} ·{' '}
                                            {r.status === 'running'
                                                ? '进行中'
                                                : r.status === 'error'
                                                  ? '失败'
                                                  : r.status === 'aborted'
                                                    ? '已停止'
                                                    : '完成'}
                                            {duration(r) && ` · ${duration(r)}`}
                                        </small>
                                    </li>
                                ))}
                            </ol>
                        </RecordCard>
                    )}
                    {session.sent.length > 0 && (
                        <RecordCard
                            icon={ReceiptText}
                            title="发送回执"
                            meta={`${session.sent.length} 条`}
                            summary="消息编号与投递结果"
                        >
                            <pre>{JSON.stringify(session.sent, null, 2)}</pre>
                        </RecordCard>
                    )}
                    {context.map((r, index) => (
                        <RecordCard
                            key={index}
                            icon={
                                r.kind === 'prompt'
                                    ? Layers
                                    : r.kind === 'reasoning'
                                      ? Brain
                                      : r.kind === 'note'
                                        ? CircleAlert
                                        : Bot
                            }
                            title={
                                r.kind === 'prompt'
                                    ? '本次输入'
                                    : r.kind === 'reasoning'
                                      ? '模型思考'
                                      : r.kind === 'note'
                                        ? '系统纠正'
                                        : '模型文字'
                            }
                            meta={`记录 ${index + 1}`}
                            summary={
                                r.kind === 'prompt'
                                    ? '角色规则与本次聊天上下文'
                                    : preview(r.text || '')
                            }
                        >
                            {r.retryOf && <p>手动重跑 · 原记录 {r.retryOf}</p>}
                            {r.messages?.map((m, i) => (
                                <Disclosure
                                    key={i}
                                    className="session-prompt-part"
                                    title={m.role === 'system' ? '角色与规则' : '聊天上下文'}
                                >
                                    <pre>{m.content}</pre>
                                </Disclosure>
                            ))}
                            {r.text && <p>{r.text}</p>}
                        </RecordCard>
                    ))}
                </div>
            </Disclosure>
        </div>
    );
}
