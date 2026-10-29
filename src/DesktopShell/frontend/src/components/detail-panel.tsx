import type { ReactNode } from 'react';

/** Keep keyed transitions inside a stable viewport, independent of loading/polls. */
export function DetailPanel({
    identity,
    children,
    className = '',
}: {
    identity: string;
    children: ReactNode;
    className?: string;
}) {
    return (
        <div className="detail-panel-frame">
            <div className="swap-enter-x" key={identity}>
                <section className={'ui-card console-panel archive-detail ' + className}>
                    {children}
                </section>
            </div>
        </div>
    );
}
