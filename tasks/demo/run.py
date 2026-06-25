"""Demo: PSE 完成代码任务。"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from autogen_pse import create_pse_team, run_task  # noqa: E402


async def main():
    team = create_pse_team(task="demo")
    task = """用 Python 实现快速排序 quicksort(arr)，创建：
1. tasks/demo/output/quicksort.py — 实现函数
2. tasks/demo/output/test_quicksort.py — 测试：空数组/单元素/已排序/逆序/重复元素/100随机元素
3. 代码通过 ruff 检查"""
    result, report = await run_task(team, task, verbose=True)
    print(report.summary())


if __name__ == "__main__":
    asyncio.run(main())
