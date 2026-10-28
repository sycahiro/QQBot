import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { UI_MOTION, cssMotionEase } from './motion';

export type Theme = 'light' | 'dark' | 'system';
let pendingWrite: Promise<unknown> = Promise.resolve();
let queuedTheme: Theme | undefined;
let awaitingBridge = false;
function flushTheme() {
    if (!window.pywebview?.api || queuedTheme === undefined) return;
    const theme = queuedTheme;
    queuedTheme = undefined;
    pendingWrite = pendingWrite
        .catch(() => {})
        .then(async () => {
            const result = await window.pywebview!.api.save_theme(theme);
            if (!result.ok) throw Error('主题保存失败');
        })
        .catch(() => console.error('主题保存失败，请重新选择主题'));
}
function saveTheme(theme: Theme) {
    window.__QQBOT_THEME__ = theme;
    window.dispatchEvent(new CustomEvent('qqbot-theme-preference', { detail: theme }));
    queuedTheme = theme;
    if (window.pywebview?.api) flushTheme();
    else if (!awaitingBridge) {
        awaitingBridge = true;
        window.addEventListener(
            'pywebviewready',
            () => {
                awaitingBridge = false;
                flushTheme();
            },
            { once: true },
        );
    }
}

function readTheme(): Theme {
    try {
        const saved = window.__QQBOT_THEME__;
        return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch {
        return 'system';
    }
}

function isDark(theme: Theme) {
    return (
        theme === 'dark' ||
        (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
    );
}

let palette: string[] | undefined;

function paletteColors(root: HTMLElement) {
    if (!palette) {
        const style = getComputedStyle(root);
        palette = Array.from(style).filter(
            (name) => name.startsWith('--') && CSS.supports('color', style.getPropertyValue(name)),
        );
        for (const name of palette) {
            // Registered colors are interpolated once on html and inherited by
            // all text, cards and scrollbar parts in the very same frame.
            CSS.registerProperty({
                name,
                syntax: '<color>',
                inherits: true,
                initialValue: style.getPropertyValue(name).trim(),
            });
        }
    }
    const style = getComputedStyle(root);
    return Object.fromEntries(palette.map((name) => [name, style.getPropertyValue(name)]));
}

// One palette animation, rather than independent transitions on nested text.
export function useTheme() {
    const [theme, commitTheme] = useState<Theme>(readTheme);
    const current = useRef(theme);
    const animation = useRef<Animation | null>(null);

    const setTheme = useCallback((next: Theme) => {
        const root = document.documentElement;
        current.current = next;
        const dark = isDark(next);
        const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
        const changed = root.classList.contains('dark') !== dark;
        if (!changed) {
            flushSync(() => commitTheme(next));
            saveTheme(next);
            return;
        }
        const animate = !reduced && !document.hidden;
        const before = animate ? paletteColors(root) : null;
        animation.current?.cancel();
        animation.current = null;
        root.classList.toggle('theme-changing', animate);
        root.classList.toggle('dark', dark);
        flushSync(() => commitTheme(next));
        saveTheme(next);
        if (before) {
            const after = paletteColors(root);
            const transition = root.animate([before, after], {
                duration: UI_MOTION.duration * 1000,
                easing: cssMotionEase,
            });
            animation.current = transition;
            void transition.finished
                .catch(() => {})
                .finally(() => {
                    if (animation.current !== transition) return;
                    animation.current = null;
                    root.classList.remove('theme-changing');
                    root.style.colorScheme = dark ? 'dark' : 'light';
                });
        } else {
            root.style.colorScheme = dark ? 'dark' : 'light';
        }
    }, []);

    useEffect(() => {
        const media = matchMedia('(prefers-color-scheme: dark)');
        const synchronize = (event: Event) => {
            const value = (event as CustomEvent<Theme>).detail;
            current.current = value;
            commitTheme(value);
        };
        window.addEventListener('qqbot-theme-preference', synchronize);
        const followSystem = () => {
            if (current.current === 'system') setTheme('system');
        };
        media.addEventListener('change', followSystem);
        return () => {
            media.removeEventListener('change', followSystem);
            window.removeEventListener('qqbot-theme-preference', synchronize);
            animation.current?.cancel();
            animation.current = null;
            document.documentElement.classList.remove('theme-changing');
        };
    }, [setTheme]);
    return { theme, setTheme };
}
