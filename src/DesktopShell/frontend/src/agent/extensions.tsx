import { Package } from 'lucide-react';

export function Extensions({ ready }: { ready: boolean }) {
    // 原项目的插件市场已停止服务（作者删库），市场浏览功能随之移除；
    // 本页保留为扩展占位，不再提供任何市场入口。
    void ready;
    return (
        <div className="tab-panel-frame">
            <div className="desktop-sections page-enter">
                <div className="archive-toolbar">
                    <p>查看已安装的插件和 Skill。</p>
                </div>
                <section className="ui-card console-panel desktop-empty">
                    <span className="empty-icon">
                        <Package size={28} />
                    </span>
                    <h3>暂无可用扩展</h3>
                    <p>原项目的插件市场已停止服务，当前没有可安装的扩展。</p>
                </section>
            </div>
        </div>
    );
}
