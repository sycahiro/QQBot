"""入站链路：准入 → 存档 → 通知调度器；由独立的开关决定是否调用模型。"""

from ..storage.messages import normalize_message
from .config import allowed


class Receiver:
    def __init__(self, settings, messages, agent=None):
        self._settings, self._messages = settings, messages
        self._agent = agent

    def receive(self, account, event):
        if event.get("post_type") == "notice" and event.get("notice_type") in (
            "group_recall",
            "friend_recall",
        ):
            # Even if a chat was removed from the allowlist, honor recalls for
            # previously stored messages so their archive status stays accurate.
            return self._messages.ingest(account, event)
        message = normalize_message(account, event)
        if message is None:
            return None
        config = self._settings.read(account)
        kind, peer = message["chatKey"].split(":", 1)
        if not allowed(kind, peer, message["senderId"], config):
            return None
        item = self._messages.ingest(account, event)
        if self._agent:
            self._agent.incoming(account, item)
        return item
