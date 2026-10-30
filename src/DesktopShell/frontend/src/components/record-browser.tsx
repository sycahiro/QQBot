import type { ReactNode } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { AnimatedList } from './animated-list';
import { DetailPanel } from './detail-panel';

type Action = { run: () => void; disabled?: boolean; loading?: boolean };

/** Common controls and placement; each page keeps its own guarded operations. */
export function RecordToolbar({
    summary,
    noun,
    remove,
    clear,
    refresh,
    removeLabel,
    actions,
}: {
    summary: ReactNode;
    noun: string;
    remove: Action;
    clear: Action;
    refresh: Action;
    removeLabel?: string;
    actions?: ReactNode;
}) {
    return (
        <div className="archive-toolbar record-toolbar">
            <p>{summary}</p>
            <div className="record-toolbar-actions">
                {actions}
                <button
                    type="button"
                    className="btn"
                    disabled={remove.disabled}
                    onClick={remove.run}
                >
                    <Trash2 size={15} />
                    {removeLabel || `删除当前${noun}`}
                </button>
                <button type="button" className="btn" disabled={clear.disabled} onClick={clear.run}>
                    <Trash2 size={15} />
                    清空全部{noun}
                </button>
                <button
                    type="button"
                    className="btn"
                    disabled={refresh.disabled}
                    onClick={refresh.run}
                >
                    <RefreshCw size={15} className={refresh.loading ? 'qq-scanning' : undefined} />
                    刷新
                </button>
            </div>
        </div>
    );
}

/** Stable two-column viewport and the same keyed transition for all record pages. */
export function RecordBrowser({
    identity,
    list,
    detailClassName,
    children,
}: {
    identity: string;
    list: ReactNode;
    detailClassName?: string;
    children: ReactNode;
}) {
    return (
        <div className="agent-split record-browser">
            <AnimatedList className="chat-card-list" staged>
                {list}
            </AnimatedList>
            <DetailPanel identity={identity} className={detailClassName}>
                {children}
            </DetailPanel>
        </div>
    );
}

export function RecordCard({
    selected,
    onSelect,
    disabled,
    title,
    subtitle,
    preview,
    meta,
    badge,
}: {
    selected: boolean;
    onSelect: () => void | Promise<void>;
    disabled?: boolean;
    title: ReactNode;
    subtitle?: ReactNode;
    preview?: ReactNode;
    meta?: ReactNode;
    badge?: ReactNode;
}) {
    return (
        <button
            type="button"
            className={`ui-card chat-list-card${selected ? ' selected' : ''}`}
            aria-pressed={selected}
            disabled={disabled}
            onClick={() => void onSelect()}
        >
            <span className="record-card-heading">
                <strong>{title}</strong>
                {badge}
            </span>
            {subtitle != null && <small>{subtitle}</small>}
            {preview != null && <p>{preview}</p>}
            {meta != null && <small>{meta}</small>}
        </button>
    );
}

export function RecordHeading({
    title,
    subtitle,
    icon,
    actions,
}: {
    title: ReactNode;
    subtitle?: ReactNode;
    icon?: ReactNode;
    actions?: ReactNode;
}) {
    return (
        <div className="console-panel-heading record-detail-heading">
            <div>
                <h2>{title}</h2>
                {subtitle != null && <p>{subtitle}</p>}
            </div>
            {actions ? <div className="record-detail-actions">{actions}</div> : icon}
        </div>
    );
}

export function RecordEmpty({
    icon,
    title,
    children,
}: {
    icon: ReactNode;
    title: ReactNode;
    children: ReactNode;
}) {
    return (
        <div className="record-empty-frame">
            <section className="ui-card console-panel desktop-empty">
                <span className="empty-icon">{icon}</span>
                <h3>{title}</h3>
                {children}
            </section>
        </div>
    );
}
