import { useEffect, useState } from 'react';
import { Bot, Boxes, Code2, ExternalLink, HeartHandshake, Monitor } from 'lucide-react';
import { Disclosure } from '../components/disclosure';
import { Notice } from '../components/notice';
import type { DependencyInventory, DependencyItem, DesktopInfo } from '../desktop';

const kinds = [
    { id: 'direct', title: '直接依赖', description: '应用清单中声明的依赖。' },
    {
        id: 'development',
        title: '开发与检查工具',
        description: '用于构建、类型检查、格式化和测试。',
    },
    {
        id: 'installed',
        title: '其他已安装组件',
        description: '包括间接依赖以及环境中额外安装的组件。',
    },
] as const;

function Packages({ title, items }: { title: string; items: DependencyItem[] }) {
    return (
        <div className="about-package-family">
            <h4>
                {title} <span>{items.length}</span>
            </h4>
            {items.length ? (
                <div className="about-package-list">
                    {items.map((item, index) => (
                        <div
                            className="about-package"
                            key={`${item.name}-${item.version}-${index}`}
                        >
                            <strong>{item.name}</strong>
                            <span>{item.version}</span>
                            <small>{item.license}</small>
                        </div>
                    ))}
                </div>
            ) : (
                <p className="about-empty">没有已记录的组件</p>
            )}
        </div>
    );
}

export function About({ info }: { info: DesktopInfo | null }) {
    const [inventory, setInventory] = useState<DependencyInventory | null>(null);
    const [failed, setFailed] = useState(false);
    const [linkError, setLinkError] = useState('');
    const openProject = async (
        project: 'python' | 'node' | 'snowluma' | 'author' | 'repo' | 'issues',
    ) => {
        try {
            const result = await window.pywebview!.api.open_project_page(project);
            if (!result.ok) setLinkError(result.error.message);
        } catch {
            setLinkError('无法打开系统浏览器，请检查浏览器设置');
        }
    };
    useEffect(() => {
        if (!info || !window.pywebview?.api) return;
        let active = true;
        setFailed(false);
        window.pywebview.api
            .get_dependencies()
            .then((result) => {
                if (!active) return;
                if (result.ok) setInventory(result);
                else setFailed(true);
            })
            .catch(() => {
                if (active) setFailed(true);
            });
        return () => {
            active = false;
        };
    }, [info]);
    return (
        <>
            <Notice
                title="打开官网失败"
                message={linkError}
                error
                onClose={() => setLinkError('')}
            />
            <section className="ui-card console-panel about-hero">
                <div className="about-hero-heading">
                    <div className="about-mark">
                        <Bot size={24} />
                    </div>
                    <div>
                        <span className="about-eyebrow">桌面工作台</span>
                        <h2>QQBot</h2>
                        <p>让本机 QQ 与 AI 助手协同工作</p>
                    </div>
                    <span className="about-version">{info ? `v${info.version}` : '读取版本…'}</span>
                </div>
                <p className="about-intro">
                    QQBot 是运行在 Windows 上的个人 QQ 助手。连接本机已登录的 QQ
                    后，可以管理自动回复、聊天存档、记忆与表情库。
                </p>
                <p className="about-intro">
                    设置与记录保存在本机；使用模型或联网搜索时，相关请求会发送到您配置的服务。
                </p>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>作者</h2>
                        <p>设计与开发</p>
                    </div>
                    <Code2 size={18} />
                </div>
                <div className="about-runtime-card">
                    <div>
                        <strong>sycahiro</strong>
                        <span>QQBot 作者与维护者</span>
                    </div>
                    <p>
                        有人在用、有人愿意折腾，这个小项目就有意义。遇到问题或想改进它，
                        欢迎到仓库提 Issue 和 PR。
                    </p>
                    <div className="about-links">
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('author')}
                            aria-label="打开作者的 GitHub 主页"
                        >
                            GitHub 主页 <ExternalLink size={12} />
                        </button>
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('repo')}
                            aria-label="打开本项目仓库"
                        >
                            项目仓库 <ExternalLink size={12} />
                        </button>
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('issues')}
                            aria-label="打开问题反馈页"
                        >
                            问题反馈 <ExternalLink size={12} />
                        </button>
                    </div>
                </div>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>运行环境</h2>
                        <p>当前安装的桌面环境和连接组件</p>
                    </div>
                    <Monitor size={18} />
                </div>
                <dl className="about-runtime">
                    <div>
                        <dt>系统</dt>
                        <dd>{info?.platform ?? '读取中'}</dd>
                    </div>
                    <div>
                        <dt>桌面窗口</dt>
                        <dd>{info?.renderer ?? '读取中'}</dd>
                    </div>
                    <div>
                        <dt>Python</dt>
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('python')}
                            aria-label="打开 Python 官网"
                        >
                            官网 <ExternalLink size={12} />
                        </button>
                        <dd>{info?.python ?? '读取中'}</dd>
                    </div>
                    <div>
                        <dt>Node.js</dt>
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('node')}
                            aria-label="打开 Node.js 官网"
                        >
                            官网 <ExternalLink size={12} />
                        </button>
                        <dd>{inventory?.nodeVersion ?? (failed ? '无法读取' : '读取中')}</dd>
                    </div>
                    <div>
                        <dt>SnowLuma</dt>
                        <button
                            className="about-official-link"
                            type="button"
                            onClick={() => void openProject('snowluma')}
                            aria-label="打开 SnowLuma 官网"
                        >
                            官网 <ExternalLink size={12} />
                        </button>
                        <dd>{info?.snowlumaVersion ?? '无法读取'}</dd>
                    </div>
                    <div>
                        <dt>联网浏览器</dt>
                        <dd>系统 Microsoft Edge</dd>
                    </div>
                </dl>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>依赖与组件</h2>
                        <p>版本和许可证来自本机已安装组件的元数据。</p>
                    </div>
                    <Boxes size={18} />
                </div>
                <p className="about-component-note">
                    组件随安装与升级变化；许可证名称仅作索引，完整版权声明和条款以各组件附带的文件为准。
                </p>
                {failed ? (
                    <p className="about-empty" role="status">
                        组件信息暂时无法读取，请检查项目运行环境。
                    </p>
                ) : !inventory ? (
                    <p className="about-empty" role="status">
                        正在读取组件信息…
                    </p>
                ) : (
                    <div className="about-dependency-groups">
                        {kinds.map((group) => {
                            const python = inventory.pythonPackages.filter(
                                (item) => item.kind === group.id,
                            );
                            const node = inventory.nodePackages.filter(
                                (item) => item.kind === group.id,
                            );
                            return (
                                <Disclosure
                                    className="about-dependency-group"
                                    key={group.id}
                                    title={
                                        <span className="about-dependency-heading">
                                            <span>
                                                <strong>{group.title}</strong>
                                                <small>{group.description}</small>
                                            </span>
                                            <b>{python.length + node.length}</b>
                                        </span>
                                    }
                                >
                                    <div className="about-package-columns">
                                        <Packages title="Python" items={python} />
                                        <Packages title="JavaScript / Node.js" items={node} />
                                    </div>
                                </Disclosure>
                            );
                        })}
                    </div>
                )}
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>第三方运行时</h2>
                        <p>连接个人 QQ 所使用的独立组件</p>
                    </div>
                    <Code2 size={18} />
                </div>
                <div className="about-runtime-card">
                    <div>
                        <strong>SnowLuma</strong>
                        <span>
                            {info?.snowlumaVersion ? `v${info.snowlumaVersion}` : '版本未知'}
                        </span>
                    </div>
                    <p>
                        由 SnowLumaDevs 开发，QQBot
                        通过独立进程与其通信。该发行包包含专有组件，适用其自身许可和最终用户许可协议。
                    </p>
                    <small>
                        发行包内的第三方组件、许可与隐私说明请查阅项目内 src/SnowLuma 的随附文件。
                    </small>
                </div>
            </section>
            <section className="ui-card console-panel">
                <div className="console-panel-heading">
                    <div>
                        <h2>致谢</h2>
                        <p>感谢开源社区与相关项目的贡献</p>
                    </div>
                    <HeartHandshake size={18} />
                </div>
                <p className="about-intro">
                    机器人业务设计和部分实现参考或改写自 QQ Agent，原项目版权及许可声明见项目 README 的
                    「许可与第三方声明」一节。感谢 SnowLuma
                    和其他第三方组件的维护者；各项目的名称、代码和许可归其各自所有者。
                </p>
            </section>
        </>
    );
}
