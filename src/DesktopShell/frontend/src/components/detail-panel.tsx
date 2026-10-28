import { uiTransition } from '../motion';
import type { ReactNode } from 'react';
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from 'motion/react';

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
            <AnimatePresence mode="wait" initial={false}>
                <DetailSurface key={identity} className={className}>
                    {children}
                </DetailSurface>
            </AnimatePresence>
        </div>
    );
}

function DetailSurface({ children, className }: { children: ReactNode; className: string }) {
    const reduced = useReducedMotion(),
        present = useIsPresent();
    return (
        <motion.section
            className={'ui-card console-panel archive-detail ' + className}
            inert={!present}
            initial={{ opacity: 0, x: reduced ? 0 : 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: reduced ? 0 : -10, pointerEvents: 'none' }}
            transition={uiTransition(reduced)}
        >
            {children}
        </motion.section>
    );
}
