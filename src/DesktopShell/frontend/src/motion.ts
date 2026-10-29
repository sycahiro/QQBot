/** One timing policy for layout, controls, notifications and theme transitions. */
export const UI_MOTION = {
    duration: 0.24,
    ease: [0.2, 0, 0.2, 1] as [number, number, number, number],
    cycle: 1,
};
export const cssMotionEase = `cubic-bezier(${UI_MOTION.ease.join(',')})`;
export function installMotionTokens() {
    const style = document.documentElement.style;
    style.setProperty('--motion-duration', `${UI_MOTION.duration}s`);
    style.setProperty('--motion-ease', cssMotionEase);
    style.setProperty('--motion-cycle', `${UI_MOTION.cycle}s`);
}
function prefersReducedMotion() {
    return (
        typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
    );
}
export function scrollToY(element: HTMLElement, top: number, complete?: () => void) {
    const target = Math.max(0, Math.min(top, element.scrollHeight - element.clientHeight));
    if (prefersReducedMotion() || element.scrollTop === target) {
        element.scrollTop = target;
        complete?.();
        return () => {};
    }
    const start = element.scrollTop,
        distance = target - start,
        duration = UI_MOTION.duration * 1000,
        begin = performance.now();
    let frame = 0;
    const step = (now: number) => {
        const progress = Math.min(1, (now - begin) / duration);
        const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
        element.scrollTop = start + distance * eased;
        if (progress < 1) frame = requestAnimationFrame(step);
        else complete?.();
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
}
