import { BookmarkPlus, Undo2 } from 'lucide-react';
import type { ArchivedMessage } from '../business';

export function ArchiveMessage({
    item,
    busy,
    onExpand,
    onCollect,
}: {
    item: ArchivedMessage;
    busy: boolean;
    onExpand: () => void;
    onCollect: () => void;
}) {
    return (
        <article
            data-message-id={item.id}
            className={
                'archive-message' +
                (item.self ? ' self' : '') +
                (item.withdrawn ? ' withdrawn' : '')
            }
        >
            <header>
                {item.self ? '我' : item.senderName || item.senderId}
                {!item.self && item.senderName !== item.senderId
                    ? `（${item.senderId}）`
                    : ''} · {new Date(item.ts).toLocaleString('zh-CN', { hour12: false })}
                {item.withdrawn ? (
                    <span className="archive-recall-badge">
                        <Undo2 size={12} aria-hidden="true" />
                        已撤回
                    </span>
                ) : (
                    !item.self && !item.read && <span className="archive-message-unread">未读</span>
                )}
            </header>
            <p>{item.text || '[空消息]'}</p>
            {item.mid && !item.withdrawn && (item.hasImage || item.hasForward) && (
                <div className="archive-message-actions">
                    {item.hasForward && !item.text.startsWith('[合并转发 共') && (
                        <button className="btn btn-sm" disabled={busy} onClick={onExpand}>
                            {busy ? '请稍候…' : '展开转发'}
                        </button>
                    )}
                    {item.hasImage && (
                        <button className="btn btn-sm" disabled={busy} onClick={onCollect}>
                            <BookmarkPlus size={13} />
                            收藏首张图片
                        </button>
                    )}
                </div>
            )}
        </article>
    );
}
