import type { ApiResult, BotConfig } from '../business';

export type Section =
    'model' | 'persona' | 'defaultPersona' | 'scope' | 'advanced' | 'search' | 'sticker';
export type SettingsDraft = {
    config: BotConfig;
    key: string;
    clearKey: boolean;
    profileId: string | null;
    profileName: string;
    keywords: string;
    lists: {
        groups: string;
        private: string;
        denyGroups: string;
        denyPrivate: string;
        blocked: string;
    };
};
type Result = ApiResult<{ account: string; config: BotConfig }>;
type State = {
    config: BotConfig;
    draft: SettingsDraft;
    saving: Section | null;
    errors: Partial<Record<Section, string>>;
    saved: Section | null;
};
type ModelDraft = Pick<SettingsDraft, 'key' | 'clearKey' | 'profileId' | 'profileName'> & {
    api: BotConfig['api'];
};
class ValidationError extends Error {}
const numbers = (text: string) => [...new Set(text.split(/[\s,，;；]+/).filter(Boolean))];
export const blankApi: BotConfig['api'] = {
    protocol: 'chat',
    sendTemperature: true,
    maxOutputTokens: 4096,
    chatTokenLimitField: 'max_tokens',
    baseUrl: '',
    model: '',
    apiKeyConfigured: false,
    temperature: 0.8,
    maxRounds: 12,
    timeoutMs: 90000,
    vision: false,
    visionModel: '',
    sendImages: false,
};

function initial(config: BotConfig): SettingsDraft {
    return {
        config,
        key: '',
        clearKey: false,
        profileId: config.activeProfileId || 'current',
        profileName:
            config.profiles.find((p) => p.id === config.activeProfileId)?.name || '默认配置',
        keywords: config.groupKeywords.join('\n'),
        lists: {
            groups: config.allow.groups.join('\n'),
            private: config.allow.private.join('\n'),
            denyGroups: config.deny.groups.join('\n'),
            denyPrivate: config.deny.private.join('\n'),
            blocked: config.blockedUsers.join('\n'),
        },
    };
}
export function draftApi(draft: SettingsDraft) {
    const { apiKeyConfigured: _, ...api } = draft.config.api;
    return {
        ...api,
        ...(draft.clearKey ? { apiKey: '' } : draft.key ? { apiKey: draft.key } : {}),
    };
}
function draftSearch(draft: SettingsDraft) {
    return { ...draft.config.webSearch };
}
function modelApi(draft: SettingsDraft) {
    const {
        protocol,
        sendTemperature,
        maxOutputTokens,
        chatTokenLimitField,
        baseUrl,
        model,
        temperature,
        maxRounds,
        timeoutMs,
        apiKey,
    } = draftApi(draft);
    return {
        protocol,
        sendTemperature,
        maxOutputTokens,
        chatTokenLimitField,
        baseUrl,
        model,
        temperature,
        maxRounds,
        timeoutMs,
        ...(apiKey === undefined ? {} : { apiKey }),
    };
}
function fields(draft: SettingsDraft, section: Section) {
    if (section === 'search') return { search: draft.config.webSearch };
    if (section === 'sticker') return { sticker: draft.config.sticker };
    if (section === 'model')
        return { api: modelApi(draft), id: draft.profileId, name: draft.profileName };
    if (section === 'persona') return { persona: draft.config.persona };
    if (section === 'defaultPersona')
        return { defaultPersona: draft.config.defaultPersona, ownerQQ: draft.config.ownerQQ };
    if (section === 'scope')
        return {
            groups: draft.lists.groups,
            private: draft.lists.private,
            keywords: draft.keywords,
            trigger: draft.config.groupTrigger,
            percent: draft.config.groupRandomPercent,
            context: draft.config.contextLimit,
        };
    return {
        groups: draft.lists.denyGroups,
        private: draft.lists.denyPrivate,
        blocked: draft.lists.blocked,
    };
}
function mergeSection(draft: SettingsDraft, saved: SettingsDraft, section: Section): SettingsDraft {
    if (section === 'search')
        return { ...draft, config: { ...draft.config, webSearch: saved.config.webSearch } };
    if (section === 'sticker')
        return { ...draft, config: { ...draft.config, sticker: saved.config.sticker } };
    if (section === 'model')
        return {
            ...draft,
            key: '',
            clearKey: false,
            profileId: saved.profileId,
            profileName: saved.profileName,
            config: {
                ...draft.config,
                api: saved.config.api,
                activeProfileId: saved.config.activeProfileId,
                profiles: saved.config.profiles,
            },
        };
    if (section === 'persona')
        return { ...draft, config: { ...draft.config, persona: saved.config.persona } };
    if (section === 'defaultPersona')
        return {
            ...draft,
            config: {
                ...draft.config,
                defaultPersona: saved.config.defaultPersona,
                ownerQQ: saved.config.ownerQQ,
            },
        };
    if (section === 'scope')
        return {
            ...draft,
            keywords: saved.keywords,
            lists: { ...draft.lists, groups: saved.lists.groups, private: saved.lists.private },
            config: {
                ...draft.config,
                groupTrigger: saved.config.groupTrigger,
                groupRandomPercent: saved.config.groupRandomPercent,
                contextLimit: saved.config.contextLimit,
            },
        };
    return {
        ...draft,
        lists: {
            ...draft.lists,
            denyGroups: saved.lists.denyGroups,
            denyPrivate: saved.lists.denyPrivate,
            blocked: saved.lists.blocked,
        },
    };
}

/** Explicit per-card saves. No timers, blur writes, or unmount writes. */
export class SettingsEditor {
    readonly account: string;
    private write: (patch: unknown, account: string) => Promise<Result>;
    private profile: (
        operation: 'save' | 'delete',
        data: unknown,
        account: string,
    ) => Promise<Result>;
    private state: State;
    private listeners = new Set<() => void>();
    private disposed = false;
    private modelDrafts = new Map<string, ModelDraft>();
    private modelKey(id: string | null) {
        return id ?? '__new__';
    }
    constructor(
        account: string,
        config: BotConfig,
        write: (patch: unknown, account: string) => Promise<Result>,
        profile: (operation: 'save' | 'delete', data: unknown, account: string) => Promise<Result>,
    ) {
        this.account = account;
        this.write = write;
        this.profile = profile;
        this.state = { config, draft: initial(config), saving: null, errors: {}, saved: null };
    }
    getSnapshot = () => this.state;
    subscribe = (fn: () => void) => {
        this.listeners.add(fn);
        return () => {
            this.listeners.delete(fn);
        };
    };
    private publish(state: State) {
        this.state = state;
        this.listeners.forEach((fn) => fn());
    }
    change(draft: SettingsDraft) {
        if (!this.disposed) this.publish({ ...this.state, draft, saved: null });
    }
    dirty(section: Section) {
        return (
            JSON.stringify(fields(this.state.draft, section)) !==
            JSON.stringify(fields(initial(this.state.config), section))
        );
    }
    reconcile(
        config: BotConfig,
        sections: Section[] = [
            'model',
            'persona',
            'defaultPersona',
            'scope',
            'advanced',
            'search',
            'sticker',
        ],
    ) {
        if (this.disposed) return;
        if (!this.state.saving && !sections.some((s) => this.dirty(s))) {
            this.publish({ ...this.state, config, draft: initial(config) });
        }
    }
    pick(id: string | null) {
        const api =
            id === null
                ? { ...blankApi }
                : id === 'current'
                  ? this.state.config.api
                  : this.state.config.profiles.find((p) => p.id === id)?.api;
        if (!api || this.state.saving || this.disposed) return;
        const draft = this.state.draft;
        if (id === draft.profileId) return;
        this.modelDrafts.set(this.modelKey(draft.profileId), {
            key: draft.key,
            clearKey: draft.clearKey,
            profileId: draft.profileId,
            profileName: draft.profileName,
            api: { ...draft.config.api },
        });
        const cached = this.modelDrafts.get(this.modelKey(id));
        if (cached) {
            const { api, ...values } = cached;
            this.change({ ...draft, ...values, config: { ...draft.config, api: { ...api } } });
            return;
        }
        this.change({
            ...this.state.draft,
            profileId: id,
            profileName:
                id === null
                    ? '新模型配置'
                    : this.state.config.profiles.find((p) => p.id === id)?.name || '默认配置',
            key: '',
            clearKey: false,
            config: { ...this.state.draft.config, api: { ...api } },
        });
    }
    async toggleSticker(field: keyof BotConfig['sticker'], value: boolean) {
        if (this.disposed || this.state.saving) return;
        const previous = this.state.draft.config.sticker[field];
        this.publish({
            ...this.state,
            saving: 'sticker',
            saved: null,
            errors: { ...this.state.errors, sticker: '' },
            draft: {
                ...this.state.draft,
                config: {
                    ...this.state.draft.config,
                    sticker: { ...this.state.draft.config.sticker, [field]: value },
                },
            },
        });
        try {
            const result = await this.write({ sticker: { [field]: value } }, this.account);
            if (this.disposed) return;
            if (!result.ok) throw new ValidationError(result.error.message);
            if (result.account !== this.account)
                throw new ValidationError('连接账号已变化，操作未确认');
            this.publish({
                ...this.state,
                config: result.config,
                saved: 'sticker',
                draft: {
                    ...this.state.draft,
                    config: { ...this.state.draft.config, sticker: result.config.sticker },
                },
            });
        } catch (error) {
            if (!this.disposed)
                this.publish({
                    ...this.state,
                    errors: {
                        ...this.state.errors,
                        sticker:
                            error instanceof ValidationError
                                ? error.message
                                : '保存失败，开关已恢复',
                    },
                    draft: {
                        ...this.state.draft,
                        config: {
                            ...this.state.draft.config,
                            sticker: { ...this.state.draft.config.sticker, [field]: previous },
                        },
                    },
                });
        } finally {
            if (!this.disposed) this.publish({ ...this.state, saving: null });
        }
    }
    async save(section: Section, remove = false) {
        if (this.disposed || this.state.saving) return;
        const snapshot = this.state.draft;
        this.publish({
            ...this.state,
            saving: section,
            saved: null,
            errors: { ...this.state.errors, [section]: '' },
        });
        try {
            let result: Result;
            if (section === 'model')
                result = await this.profile(
                    remove ? 'delete' : 'save',
                    remove
                        ? { id: snapshot.profileId }
                        : {
                              id: snapshot.profileId === 'current' ? '' : snapshot.profileId,
                              name: snapshot.profileName,
                              api: modelApi(snapshot),
                          },
                    this.account,
                );
            else {
                const patch =
                    section === 'search'
                        ? { webSearch: draftSearch(snapshot) }
                        : section === 'sticker'
                          ? { sticker: snapshot.config.sticker }
                          : section === 'persona'
                            ? { persona: snapshot.config.persona }
                            : section === 'defaultPersona'
                              ? { defaultPersona: snapshot.config.defaultPersona }
                              : section === 'scope'
                                ? {
                                      allow: {
                                          groups: numbers(snapshot.lists.groups),
                                          private: numbers(snapshot.lists.private),
                                      },
                                      groupTrigger: snapshot.config.groupTrigger,
                                      groupKeywords: snapshot.keywords
                                          .split(/\r?\n/)
                                          .map((w) => w.trim())
                                          .filter(Boolean),
                                      groupRandomPercent: snapshot.config.groupRandomPercent,
                                      contextLimit: snapshot.config.contextLimit,
                                  }
                                : {
                                      deny: {
                                          groups: numbers(snapshot.lists.denyGroups),
                                          private: numbers(snapshot.lists.denyPrivate),
                                      },
                                      blockedUsers: numbers(snapshot.lists.blocked),
                                  };
                result = await this.write(patch, this.account);
            }
            if (this.disposed) return;
            if (!result.ok) throw new ValidationError(result.error.message);
            if (result.account !== this.account)
                throw new ValidationError('账号已变化，请重新打开机器人设置');
            if (section === 'model') this.modelDrafts.delete(this.modelKey(snapshot.profileId));
            const latest = this.state.draft;
            const unchanged =
                JSON.stringify(fields(latest, section)) ===
                JSON.stringify(fields(snapshot, section));
            let draft = unchanged ? mergeSection(latest, initial(result.config), section) : latest;
            if (section === 'model' && !unchanged && !remove) {
                // The submitted key is now stored; retain only genuinely newer key edits.
                draft = {
                    ...draft,
                    profileId: result.config.activeProfileId,
                    config: {
                        ...draft.config,
                        api: {
                            ...draft.config.api,
                            apiKeyConfigured: result.config.api.apiKeyConfigured,
                        },
                    },
                    ...(draft.key === snapshot.key && draft.clearKey === snapshot.clearKey
                        ? { key: '', clearKey: false }
                        : {}),
                };
            }
            this.publish({ ...this.state, config: result.config, draft, saved: section });
        } catch (error) {
            if (!this.disposed)
                this.publish({
                    ...this.state,
                    errors: {
                        ...this.state.errors,
                        [section]:
                            error instanceof ValidationError
                                ? error.message
                                : '保存结果未确认，草稿已保留，请手动重试',
                    },
                });
        } finally {
            if (!this.disposed) this.publish({ ...this.state, saving: null });
        }
    }
    dispose() {
        this.disposed = true;
        this.modelDrafts.clear();
        this.listeners.clear();
        this.state = { ...this.state, draft: { ...this.state.draft, key: '', clearKey: false } };
    }
}
