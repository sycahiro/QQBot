import { useLayoutEffect, useRef } from 'react';
import type { ArchivedMessage } from '../business';
import { AnimatedList } from '../components/animated-list';
import { ArchiveMessage } from './archive-message';
import { MessageScroll, type MessageMetrics } from './message-scroll';

/** Only this viewport scrolls; the chat title/search/count stay outside it. */
export function ArchiveMessages({
    items,
    loaded,
    query,
    history,
    busy,
    onExpand,
    onCollect,
}: {
    items: ArchivedMessage[];
    loaded: boolean;
    query: string;
    history: boolean;
    busy: boolean;
    onExpand: (item: ArchivedMessage) => void;
    onCollect: (item: ArchivedMessage) => void;
}) {
    const viewport = useRef<HTMLDivElement>(null),
        content = useRef<HTMLDivElement>(null);
    const controller = useRef(new MessageScroll(!query)).current;
    const state = useRef({ loaded, history });
    state.current = { loaded, history };
    const previousHistory = useRef(history);
    function measure(): MessageMetrics | null {
        const element = viewport.current;
        if (!element) return null;
        const top = element.getBoundingClientRect().top;
        const rows = Array.from(element.querySelectorAll<HTMLElement>('[data-message-id]')).map(
            (article) => {
                const row = (
                    article.closest('.animated-list-item') || article
                ).getBoundingClientRect();
                return {
                    id: article.dataset.messageId!,
                    top: row.top - top,
                    bottom: row.bottom - top,
                };
            },
        );
        return {
            top: element.scrollTop,
            height: element.clientHeight,
            total: element.scrollHeight,
            rows,
        };
    }
    function align() {
        const view = measure(),
            element = viewport.current;
        if (!view || !element) return;
        const top = controller.position(view, state.current.loaded);
        if (top !== null) element.scrollTop = top;
        const next = measure();
        if (next) controller.remember(next);
    }
    useLayoutEffect(() => {
        const view = measure();
        if (history !== previousHistory.current) {
            if (history && view) controller.pause(view);
            else controller.latest();
            previousHistory.current = history;
        }
        align();
    }, [items, loaded, history]);
    useLayoutEffect(() => {
        const observer = new ResizeObserver(align);
        if (viewport.current) observer.observe(viewport.current);
        if (content.current) observer.observe(content.current);
        return () => observer.disconnect();
    }, []);
    return (
        <div
            ref={viewport}
            className="archive-message-viewport"
            tabIndex={0}
            aria-label="聊天消息记录"
            onScroll={() => {
                const view = measure();
                if (view) controller.scrolled(view);
            }}
        >
            <div ref={content}>
                <AnimatedList className="archive-message-list" staged>
                    {items.map((item) => (
                        <ArchiveMessage
                            key={item.id}
                            item={item}
                            busy={busy}
                            onExpand={() => onExpand(item)}
                            onCollect={() => onCollect(item)}
                        />
                    ))}
                </AnimatedList>
                {!items.length && (
                    <p className="action-notice">
                        {!loaded
                            ? '正在读取消息…'
                            : query
                              ? '没有找到匹配消息，换个关键词试试。'
                              : '暂无消息'}
                    </p>
                )}
            </div>
        </div>
    );
}
