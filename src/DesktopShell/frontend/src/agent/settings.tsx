import { Configuration } from '../settings/configuration';

export function BotSettings({ ready, account }: { ready: boolean; account?: string }) {
    return <Configuration ready={ready} account={account} scope="bot" />;
}
