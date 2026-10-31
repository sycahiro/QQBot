import type { Session, SessionRecord } from '../business';

export const statusNames = {
    running: '处理中',
    done: '已回复',
    noreply: '未发送',
    error: '处理失败',
    aborted: '已停止',
};
export function sessionOutcome(session: Session) {
    if (session.status === 'error' && session.sent.length) return '已发送，后续处理异常';
    if (session.status === 'aborted' && session.sent.length) return '已发送，处理已停止';
    return statusNames[session.status];
}
export function requestCount(session: Session) {
    // Usage counts successful billed responses.
    // Attempt records additionally cover rejected, cancelled and in-flight calls.
    return (
        session.usage.calls +
        (session.records ?? []).filter((r) => r.kind === 'model_request' && r.status !== 'done')
            .length
    );
}
export function duration(record: Pick<SessionRecord, 'started' | 'ended'>) {
    return typeof record.started === 'number' && typeof record.ended === 'number'
        ? `${Math.max(0, (record.ended - record.started) / 1000).toFixed(1)} 秒`
        : '';
}
