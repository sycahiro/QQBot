"""tests/agent 共享 fixture 注册点。

pytest 从本模块命名空间收集 fixture；在这里导入一次，目录内全部测试即可
按参数名使用，无需在每个测试文件里重复导入（导入即注册，删除会丢 fixture）。
"""

from test_agent import stack  # noqa: F401
from test_storage import stores  # noqa: F401
