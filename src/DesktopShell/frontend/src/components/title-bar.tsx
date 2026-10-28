import { useEffect, useRef, useState } from 'react';
import { Bot, Minus, Square, Copy, X } from 'lucide-react';
import { Notice } from './notice';
// Matches desktop/frame.py WindowFrame.EDGES.
const RESIZE_EDGES = ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se'] as const;

export function TitleBar() {
    const [ready, setReady] = useState(false),
        [maximized, setMaximized] = useState(false),
        [error, setError] = useState('');
    const working = useRef(false);
    useEffect(() => {
        let active = true,
            timer: number;
        const update = async () => {
            if (!window.pywebview?.api) return;
            if (active) setReady(true);
            try {
                const result = await window.pywebview.api.window_control('state');
                if (active && result.ok) setMaximized(result.maximized);
            } catch {}
        };
        const resized = () => {
            clearTimeout(timer);
            timer = window.setTimeout(() => void update(), 80);
        };
        void update();
        window.addEventListener('pywebviewready', update);
        window.addEventListener('resize', resized);
        return () => {
            active = false;
            clearTimeout(timer);
            window.removeEventListener('pywebviewready', update);
            window.removeEventListener('resize', resized);
        };
    }, []);
    async function action(name: string) {
        if (!ready || working.current) return;
        working.current = true;
        try {
            const result = await window.pywebview!.api.window_control(name);
            if (result.ok) setMaximized(result.maximized);
            else setError(result.error.message);
        } catch {
            setError('窗口操作未完成，请重试');
        } finally {
            working.current = false;
        }
    }
    return (
        <>
            <header className="window-titlebar" aria-label="窗口标题栏">
                <div
                    className="window-titlebar-drag"
                    onMouseDown={(event) => {
                        if (event.button === 0 && event.detail < 2) void action('drag');
                    }}
                    onDoubleClick={() => void action('toggle_maximize')}
                >
                    <span className="window-titlebar-logo">
                        <Bot size={18} />
                    </span>
                    <span>QQBot</span>
                </div>
                <div className="window-caption-buttons">
                    <button
                        disabled={!ready}
                        aria-label="最小化"

                        onClick={() => void action('minimize')}
                    >
                        <Minus size={17} />
                    </button>
                    <button
                        disabled={!ready}
                        aria-label={maximized ? '还原窗口' : '最大化'}

                        onClick={() => void action('toggle_maximize')}
                    >
                        {maximized ? <Copy size={14} /> : <Square size={15} />}
                    </button>
                    <button
                        disabled={!ready}
                        className="window-caption-close"
                        aria-label="关闭窗口"

                        onClick={() => void action('close')}
                    >
                        <X size={19} />
                    </button>
                </div>
            </header>
            {!maximized &&
                ready &&
                RESIZE_EDGES.map((edge) => (
                    <div
                        key={edge}
                        className={'window-resize-edge ' + edge}
                        aria-hidden="true"
                        onPointerDown={(event) => {
                            if (event.button === 0) {
                                event.preventDefault();
                                void action('resize_' + edge);
                            }
                        }}
                    />
                ))}
            <Notice title="窗口操作" message={error} onClose={() => setError('')} />
        </>
    );
}
