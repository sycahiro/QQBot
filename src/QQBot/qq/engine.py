"""引擎错误类型；引擎实现见 snowluma.py（旧 Node 管道客户端已随 qq-engine 退役）。"""


class EngineError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    @property
    def message(self):
        return str(self)
