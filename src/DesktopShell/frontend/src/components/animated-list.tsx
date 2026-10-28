import { uiTransition } from '../motion';
import { Children, useRef, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

/** Animate keyed entries, not the polling response or the whole page. */
export function AnimatedList({
    children,
    className,
    staged = false,
}: {
    children: ReactNode;
    className?: string;
    staged?: boolean;
}) {
    const reduced = useReducedMotion();
    const entries = Children.toArray(children);
    const firstKeys = useRef<Set<string | number> | null>(null);
    const getKey = (child: (typeof entries)[number]) =>
        typeof child === 'object' && 'key' in child ? (child.key ?? String(child)) : String(child);
    if (entries.length && firstKeys.current === null)
        firstKeys.current = new Set(entries.map(getKey));
    return (
        <motion.div
            className={className}
            initial={staged && !reduced ? { opacity: 0, x: 28 } : false}
            animate={
                staged && !entries.length
                    ? { opacity: 0, x: reduced ? 0 : 28 }
                    : { opacity: 1, x: 0 }
            }
            transition={uiTransition(reduced)}
        >
            <AnimatePresence>
                {entries.map((child) => {
                    const key =
                        typeof child === 'object' && 'key' in child ? child.key : String(child);
                    const initialBatch = firstKeys.current?.has(getKey(child));
                    // Fractional rows avoid temporary height:auto measurements that
                    // clamp a scroller before its removal animation can start.
                    return (
                        <motion.div
                            key={key}
                            className="animated-list-item"
                            initial="hidden"
                            animate="visible"
                            exit="removed"
                            variants={{
                                hidden: {
                                    gridTemplateRows: reduced || initialBatch ? '1fr' : '0fr',
                                },
                                visible: { gridTemplateRows: '1fr' },
                                removed: {
                                    gridTemplateRows: reduced ? '1fr' : '0fr',
                                    transition: uiTransition(reduced),
                                },
                            }}
                            transition={uiTransition(reduced)}
                        >
                            <div className="animated-list-clip">
                                <motion.div
                                    className="animated-list-content"
                                    variants={{
                                        hidden: {
                                            opacity: initialBatch ? 1 : 0,
                                            x: staged && !reduced && !initialBatch ? 28 : 0,
                                        },
                                        visible: {
                                            opacity: 1,
                                            x: 0,
                                            transition: uiTransition(reduced),
                                        },
                                        removed: {
                                            opacity: 0,
                                            x: staged && !reduced ? 18 : 0,
                                            transition: uiTransition(reduced),
                                        },
                                    }}
                                >
                                    {child}
                                </motion.div>
                            </div>
                        </motion.div>
                    );
                })}
            </AnimatePresence>
        </motion.div>
    );
}
