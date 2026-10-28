import { uiTransition } from '../motion';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
    Check,
    Cpu,
    Globe,
    HardDrive,
    Image,
    Info,
    Monitor,
    Moon,
    SlidersHorizontal,
    Sun,
    UserRound,
} from 'lucide-react';
import type { DesktopInfo } from '../desktop';
import type { Theme } from '../theme';
import { ResidenceSettings } from '../residence';
import { useTabNavigation } from '../components/tab-navigation';
import { Configuration } from './configuration';
import { About } from './about';
import { MediaSettings } from './media';
import { NetworkSettings } from './network';
import { StorageSettings } from './storage';

const tabs = [
    { id: 'general', label: '通用', icon: SlidersHorizontal },
    { id: 'model', label: '模型 API', icon: Cpu },
    { id: 'persona', label: '默认人设', icon: UserRound },
    { id: 'media', label: '图片处理', icon: Image },
    { id: 'search', label: '联网', icon: Globe },
    { id: 'storage', label: '存储', icon: HardDrive },
    { id: 'about', label: '关于', icon: Info },
] as const;
export function SystemSettings({
    info,
    theme,
    setTheme,
}: {
    info: DesktopInfo | null;
    theme: Theme;
    setTheme: (theme: Theme) => void;
}) {
    const { tab, setTab, panel, minHeight, onExitComplete } =
        useTabNavigation<(typeof tabs)[number]['id']>('general');
    const reduced = useReducedMotion();
    return (
        <div className="desktop-sections">
            <nav className="agent-tabs" aria-label="系统设置分类">
                {tabs.map(({ id, label, icon: Icon }) => (
                    <button
                        key={id}
                        aria-current={tab === id ? 'page' : undefined}
                        onClick={() => setTab(id)}
                    >
                        <Icon size={16} />
                        {label}
                    </button>
                ))}
            </nav>
            <div className="tab-panel-frame" ref={panel} style={{ minHeight }}>
                <AnimatePresence mode="wait" initial={false} onExitComplete={onExitComplete}>
                    <motion.div
                        className="desktop-sections"
                        key={tab}
                        initial={{ opacity: 0, y: reduced ? 0 : 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: reduced ? 0 : -4 }}
                        transition={uiTransition(reduced)}
                    >
                        {tab === 'general' ? (
                            <>
                                <section className="ui-card console-panel">
                                    <div className="console-panel-heading">
                                        <div>
                                            <h2>外观</h2>
                                            <p>选择工作台的明暗主题</p>
                                        </div>
                                        <SlidersHorizontal size={18} />
                                    </div>
                                    <div className="theme-options">
                                        {(
                                            [
                                                { id: 'light', label: '浅色', icon: Sun },
                                                { id: 'dark', label: '深色', icon: Moon },
                                                { id: 'system', label: '跟随系统', icon: Monitor },
                                            ] as const
                                        ).map(({ id, label, icon: Icon }) => (
                                            <button
                                                key={id}
                                                className={
                                                    'theme-option' +
                                                    (theme === id ? ' selected' : '')
                                                }
                                                aria-pressed={theme === id}
                                                onClick={() => setTheme(id)}
                                            >
                                                <Icon size={20} />
                                                <strong>{label}</strong>
                                                {theme === id && <Check size={16} />}
                                            </button>
                                        ))}
                                    </div>
                                </section>
                                <ResidenceSettings ready={Boolean(info)} />
                            </>
                        ) : tab === 'about' ? (
                            <About info={info} />
                        ) : tab === 'media' ? (
                            <MediaSettings ready={Boolean(info)} />
                        ) : tab === 'search' ? (
                            <NetworkSettings ready={Boolean(info)} />
                        ) : tab === 'storage' ? (
                            <StorageSettings ready={Boolean(info)} />
                        ) : tab === 'persona' ? (
                            <Configuration ready={Boolean(info)} scope="global" panel="persona" />
                        ) : (
                            <Configuration ready={Boolean(info)} scope="global" />
                        )}
                    </motion.div>
                </AnimatePresence>
            </div>
        </div>
    );
}
