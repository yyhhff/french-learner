@echo off
chcp 65001 >nul
REM 呀呀法语 — 本地语音识别服务启动脚本
REM 默认使用 Whisper small 模型（约 470MB），首次运行需联网下载一次；之后离线可用。
REM 如需回退轻量 tiny 模型：设置环境变量 YAYA_ASR_MODEL=tiny 后再启动。

cd /d "%~dp0.."

if not exist ".venv-asr\Scripts\python.exe" (
  echo [错误] 未找到 .venv-asr 虚拟环境，请先执行环境安装（见 README「语音服务安装」）。
  pause
  exit /b 1
)

echo 正在启动本地语音识别服务（端口 8010）…
echo 首次启动会加载模型，可能需要几十秒，请耐心等待。
".venv-asr\Scripts\python.exe" asr_service\server.py
pause
