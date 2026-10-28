import { uiTransition } from '../motion';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Package, Store } from 'lucide-react';
import { useTabNavigation } from '../components/tab-navigation';
import { Market } from './market';

export function Extensions({ ready }: { ready: boolean }) {
    const { tab, setTab, panel, minHeight, onExitComplete } = useTabNavigation<
        'extensions' | 'market'
    >('extensions');
    const reduced = useReducedMotion();
    return (
        <div ref={panel} style={{ minHeight }} className="tab-panel-frame">
            <AnimatePresence mode="wait" initial={false} onExitComplete={onExitComplete}>
                <motion.div
                    key={tab}
                    className="desktop-sections"
                    initial={{ opacity: 0, x: reduced ? 0 : 18 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: reduced ? 0 : -12, pointerEvents: 'none' }}
                    transition={uiTransition(reduced)}
                >
                    {tab === 'market' ? (
                        <Market ready={ready} onBack={() => setTab('extensions')} />
                    ) : (
                        <>
                            <div className="archive-toolbar">
                                <p>浏览原项目的插件和 Skill 目录。</p>
                                <button className="qq-refresh" onClick={() => setTab('market')}>
                                    <Store size={15} />
                                    插件市场
                                </button>
                            </div>
                            <section className="ui-card console-panel desktop-empty">
                                <span className="empty-icon">
                                    <Package size={28} />
                                </span>
                                <h3>暂无可用扩展</h3>
                                <p>当前市场仅供浏览。</p>
                            </section>
                        </>
                    )}
                </motion.div>
            </AnimatePresence>
        </div>
    );
}
