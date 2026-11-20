"""tests 包引导：把 backend 目录加入 sys.path，使 discover/pytest/直跑均可 import pron_coach 等模块。

教训来源：Python 3.11 移除 namespace package 的 discover 支持，无 __init__.py 时
`unittest discover -s tests` 报 "Start directory is not importable"（夜报 2026-11-20 NB-004）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
