import React from 'react';
import { createRoot } from 'react-dom/client';
import { DesktopShell } from './shell';
import { ConfirmationProvider } from './components/confirmation';
import { TitleBar } from './components/title-bar';
import { NoticeHost } from './components/notice';
import './styles/theme.css';
import './styles/console.css';
import './styles/desktop.css';
import { installMotionTokens } from './motion';

installMotionTokens();

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: boolean }> {
    state = { error: false };
    static getDerivedStateFromError() {
        return { error: true };
    }
    render() {
        return this.state.error ? (
            <main className="startup-error">
                <h1>界面暂时无法显示</h1>
                <p>请关闭窗口后重新启动。现有账号与聊天数据不会因此被清理。</p>
            </main>
        ) : (
            this.props.children
        );
    }
}

createRoot(document.getElementById('root')!).render(
    <>
        <TitleBar />
        <ErrorBoundary>
            <ConfirmationProvider>
                <DesktopShell />
                <NoticeHost />
            </ConfirmationProvider>
        </ErrorBoundary>
    </>,
);
