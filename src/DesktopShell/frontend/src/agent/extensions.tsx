import { Package, Store } from 'lucide-react';
import { useTabNavigation } from '../components/tab-navigation';
import { Market } from './market';

export function Extensions({ ready }: { ready: boolean }) {
    const { tab, setTab, panel } = useTabNavigation<'extensions' | 'market'>('extensions');
    return (
        <div ref={panel} className="tab-panel-frame">
            <div className="desktop-sections page-enter" key={tab}>
                {tab === 'market' ? (
                    <Market ready={ready} onBack={() => setTab('extensions')} />
                ) : (
                    <>
                        <div className="archive-toolbar">
                            <p>浏览原项目的插件和 Skill 目录。</p>
                            <button className="btn" onClick={() => setTab('market')}>
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
            </div>
        </div>
    );
}
