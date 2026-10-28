import { animate } from 'motion/react';

/** One timing policy for layout, controls, notifications and theme transitions. */
export const UI_MOTION = {
    duration: 0.24,
    ease: [0.2, 0, 0.2, 1] as [number, number, number, number],
    cycle: 1,
};
export const uiTransition = (reduced: boolean | null) => ({
    type: 'tween' as const,
    duration: reduced ? 0 : UI_MOTION.duration,
    ease: UI_MOTION.ease,
});
export const cssMotionEase = `cubic-bezier(${UI_MOTION.ease.join(',')})`;
export function installMotionTokens() {
    const style = document.documentElement.style;
    style.setProperty('--motion-duration', `${UI_MOTION.duration}s`);
    style.setProperty('--motion-ease', cssMotionEase);
    style.setProperty('--motion-cycle', `${UI_MOTION.cycle}s`);
}
export function scrollToY(
    element: HTMLElement,
    top: number,
    reduced: boolean | null,
    complete?: () => void,
) {
    const target = Math.max(0, Math.min(top, element.scrollHeight - element.clientHeight));
    if (reduced || element.scrollTop === target) {
        element.scrollTop = target;
        complete?.();
        return () => {};
    }
    const animation = animate(element.scrollTop, target, {
        ...uiTransition(false),
        onUpdate: (value) => {
            element.scrollTop = value;
        },
        onComplete: complete,
    });
    return () => animation.stop();
}
