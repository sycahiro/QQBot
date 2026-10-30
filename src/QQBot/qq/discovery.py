"""QQ 检测错误类型；检测实现见 snowluma.py（旧 Node --list 扫描已随 qq-engine 退役）。"""


class DiscoveryError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
