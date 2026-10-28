import { uiTransition } from '../motion';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

/** 状态文案切换时做一次短促的淡入淡出，避免状态直接跳变。 */
export function StatusSwap({ text, className }: { text: string; className?: string }) {
    const reduced = useReducedMotion();
    return (
        <AnimatePresence mode="wait" initial={false}>
            <motion.span
                key={text}
                className={className}
                initial={reduced ? false : { opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: reduced ? 0 : -4 }}
                transition={uiTransition(reduced)}
            >
                {text}
            </motion.span>
        </AnimatePresence>
    );
}
