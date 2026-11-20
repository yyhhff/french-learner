@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title 呀呀法语 - 一键启动

REM ============================================================
REM 呀呀法语 一键启动脚本
REM 功能：启动前自检 -> 拉起 语音服务(8011) + 后端(8000，被占自动回退) -> 健康检查 -> 打开浏览器
REM 可选环境变量（不设则用默认值）：
REM   YAYA_PYTHON       后端 Python 解释器全路径（默认自动探测：WorkBuddy 3.13 -> 系统 Python）
REM   YAYA_ASR_MODEL    语音识别模型 tiny/small（默认 small，详见 asr_service\start_asr.bat）
REM   YAYA_KEY_REG_PATH API key 注册表查询路径（默认 HKCU\Environment，仅测试用）
REM   YAYA_DOTENV       .env 文件路径（默认 backend\.env，仅测试用）
REM   YAYA_NO_BROWSER   设为 1 则启动完成后不自动打开浏览器
REM   YAYA_BACKEND_PORT 后端端口（默认 8000；被其他程序占用时自动改用 8001-8019 空闲端口；手动指定则不回退）
REM ============================================================

set "FAILS=0"

echo.
echo ============================================
echo   呀呀法语 YaYa French - 一键启动
echo ============================================
echo.

REM ---------- [1/5] 后端解释器 ----------
echo [1/5] 检查后端解释器 ...
set "PY="
if defined YAYA_PYTHON if exist "%YAYA_PYTHON%" (
  "%YAYA_PYTHON%" -c "import fastapi, uvicorn" >nul 2>nul && set "PY=%YAYA_PYTHON%"
)
if not defined PY (
  for /d %%v in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if not defined PY if exist "%%v\python.exe" (
      "%%v\python.exe" -c "import fastapi, uvicorn" >nul 2>nul && set "PY=%%v\python.exe"
    )
  )
)
if not defined PY (
  python -c "import fastapi, uvicorn" >nul 2>nul && set "PY=python"
)
if defined PY (
  echo   [OK] 后端解释器：!PY!
) else (
  echo   [FAIL] 未找到带 fastapi+uvicorn 的 Python，无法启动后端。
  echo        修复方式任选其一：
  echo        a. set YAYA_PYTHON=你的python.exe 全路径 后重跑本脚本
  echo        b. 先安装依赖：python -m pip install -r backend\requirements.txt
  set /a FAILS+=1
)

REM ---------- [2/5] 语音服务环境 ----------
echo [2/5] 检查语音服务环境 ...
set "ASR_PY=%~dp0.venv-asr\Scripts\python.exe"
if exist "%ASR_PY%" (
  "%ASR_PY%" -c "import faster_whisper, edge_tts" >nul 2>nul
  if errorlevel 1 (
    echo   [FAIL] .venv-asr 存在但依赖缺失，请参考 README「语音服务安装」重建。
    set /a FAILS+=1
  ) else (
    echo   [OK] 语音环境就绪：.venv-asr
  )
) else (
  echo   [FAIL] 未找到 .venv-asr 虚拟环境，请参考 README「语音服务安装」。
  set /a FAILS+=1
)

REM ---------- [3/5] API key ----------
echo [3/5] 检查 ZHIPU_API_KEY ...
if not defined YAYA_KEY_REG_PATH set "YAYA_KEY_REG_PATH=HKCU\Environment"
if not defined YAYA_DOTENV set "YAYA_DOTENV=%~dp0backend\.env"
set "KEYSRC="
if defined ZHIPU_API_KEY if not "%ZHIPU_API_KEY%"=="" set "KEYSRC=当前进程环境变量"
if not defined KEYSRC (
  for /f "tokens=2,*" %%a in ('reg query "%YAYA_KEY_REG_PATH%" /v ZHIPU_API_KEY 2^>nul ^| findstr /i "ZHIPU_API_KEY"') do (
    if not "%%b"=="" (
      set "ZHIPU_API_KEY=%%b"
      set "KEYSRC=用户注册表 HKCU"
    )
  )
)
if not defined KEYSRC if exist "%YAYA_DOTENV%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%YAYA_DOTENV%") do (
    if /i "%%a"=="ZHIPU_API_KEY" if not "%%b"=="" (
      set "ZHIPU_API_KEY=%%b"
      set "KEYSRC=backend\.env"
    )
    if /i "%%a"=="GLM_API_KEY" if not "%%b"=="" if not defined GLM_API_KEY (
      set "GLM_API_KEY=%%b"
      if not defined KEYSRC set "KEYSRC=backend\.env"
    )
  )
)
if defined KEYSRC (
  echo   [OK] API key 已找到，来源：!KEYSRC!，AI 重述将使用智谱 GLM
  echo        注：key 不回显；GLM 不可用时后端自动降级本地规则
) else (
  echo   [WARN] 未找到 API key，将使用本地规则重述（降级模式，不影响启动）
  echo        如需 AI 重述：设置环境变量 ZHIPU_API_KEY 或填写 backend\.env
)

REM ---------- [4/5] 端口检查 ----------
echo [4/5] 检查后端端口 / 语音端口 8011 ...
set "BACKEND_ACTION=launch"
set "ASR_ACTION=launch"
if defined YAYA_BACKEND_PORT (
  set "BACKEND_PORT=%YAYA_BACKEND_PORT%"
  set "BACKEND_PORT_MANUAL=1"
) else (
  set "BACKEND_PORT=8000"
)
call :check_backend_port
call :check_port 8011 "http://127.0.0.1:8011/health" ASR_ACTION

REM ---------- [5/5] 文件齐全性 ----------
echo [5/5] 检查前端与语料文件 ...
if exist "frontend\index.html" (
  echo   [OK] frontend\index.html
) else (
  echo   [FAIL] 缺 frontend\index.html，前端无法加载。
  set /a FAILS+=1
)
if exist "data\input\texts.json" (
  echo   [OK] data\input\texts.json
) else (
  echo   [WARN] 缺 data\input\texts.json，分级阅读将为空，不影响对话功能
)

echo.
if %FAILS% gtr 0 (
  echo ============================================
  echo   自检未通过（%FAILS% 项 FAIL），已中止启动。
  echo   按上方提示修复后重跑本脚本。
  echo ============================================
  exit /b 1
)
if "%BACKEND_ACTION%"=="quit" goto user_quit
if "%ASR_ACTION%"=="quit" goto user_quit

REM ---------- 启动 ----------
if not "%ASR_ACTION%"=="reuse" (
  echo 正在启动语音服务（窗口 YaYa-ASR，首次加载模型需几十秒）...
  start "YaYa-ASR" /D "%~dp0" cmd /k ""%ASR_PY%" asr_service\server.py"
)
if not "%BACKEND_ACTION%"=="reuse" (
  echo 正在启动后端（窗口 YaYa-Backend）...
  start "YaYa-Backend" /D "%~dp0backend" cmd /k ""%PY%" -m uvicorn app:app --host 0.0.0.0 --port !BACKEND_PORT!"
)

REM ---------- 健康检查 ----------
echo.
echo 等待服务就绪（最多约 90 秒）...
set "BACKEND_UP=0"
set "ASR_UP=0"
call :wait_http "后端 !BACKEND_PORT!" "http://127.0.0.1:!BACKEND_PORT!/api/health" 30 && set "BACKEND_UP=1"
call :wait_http "语音 8011" "http://127.0.0.1:8011/health" 45 && set "ASR_UP=1"

if "%BACKEND_UP%"=="1" if not defined YAYA_NO_BROWSER start "" http://localhost:!BACKEND_PORT!/

echo.
echo ============================================
echo   启动完成
echo   学习入口： http://localhost:!BACKEND_PORT!/
if defined KEYSRC (
  echo   AI 重述：智谱 GLM 模式
) else (
  echo   AI 重述：本地规则降级模式（缺 API key）
)
if "%ASR_UP%"=="0" echo   [WARN] 语音服务未就绪：语音识别/合成暂不可用，其余功能正常
echo   停止方式：关闭 YaYa-Backend 与 YaYa-ASR 两个窗口
echo ============================================
echo.
exit /b 0

:user_quit
echo.
echo 已按你的选择退出，未做任何改动。
exit /b 0

REM ============================================================
REM 子过程
REM ============================================================

:check_port
REM %1=端口 %2=健康检查 URL %3=动作变量名 launch/reuse/quit
set "%~3=launch"
netstat -ano | findstr /r /c:":%1 .*LISTENING" >nul 2>nul
if errorlevel 1 (
  echo   [OK] 端口 %1 空闲
  exit /b 0
)
set "CODE="
for /f %%c in ('curl -s -o nul -w "%%{http_code}" --max-time 3 "%~2"') do set "CODE=%%c"
if "%CODE%"=="200" (
  echo   [WARN] 端口 %1 已有呀呀法语服务在运行
  choice /c RKQ /n /m "        [R]重启 [K]复用不再启动 [Q]退出脚本: "
  if errorlevel 3 (
    set "%~3=quit"
    exit /b 0
  )
  if errorlevel 2 (
    set "%~3=reuse"
    exit /b 0
  )
  call :kill_port %1
  echo   [OK] 端口 %1 旧进程已结束，稍后将重新启动
  exit /b 0
)
echo   [FAIL] 端口 %1 被其他程序占用，HTTP 状态 !CODE!
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%1 .*LISTENING"') do echo        占用 PID：%%p，可用 taskkill /f /pid %%p 处理
set /a FAILS+=1
exit /b 0

:check_backend_port
REM 后端端口检查：被呀呀自身占用则询问 R/K/Q；被其他程序占用则自动回退（手动指定时不回退）
netstat -ano | findstr /r /c:":!BACKEND_PORT! .*LISTENING" >nul 2>nul
if errorlevel 1 (
  echo   [OK] 后端端口 !BACKEND_PORT! 空闲
  exit /b 0
)
set "CODE="
for /f %%c in ('curl -s -o nul -w "%%{http_code}" --max-time 3 "http://127.0.0.1:!BACKEND_PORT!/api/health"') do set "CODE=%%c"
if "%CODE%"=="200" (
  echo   [WARN] 端口 !BACKEND_PORT! 已有呀呀法语后端在运行
  choice /c RKQ /n /m "        [R]重启 [K]复用不再启动 [Q]退出脚本: "
  if errorlevel 3 (
    set "BACKEND_ACTION=quit"
    exit /b 0
  )
  if errorlevel 2 (
    set "BACKEND_ACTION=reuse"
    exit /b 0
  )
  call :kill_port !BACKEND_PORT!
  echo   [OK] 端口 !BACKEND_PORT! 旧进程已结束，稍后将重新启动
  exit /b 0
)
echo   [WARN] 后端端口 !BACKEND_PORT! 被其他程序占用（HTTP 状态 !CODE!）
if defined BACKEND_PORT_MANUAL (
  echo   [FAIL] 已手动指定 YAYA_BACKEND_PORT=!BACKEND_PORT!，不做自动回退。
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":!BACKEND_PORT! .*LISTENING"') do echo        占用 PID：%%p，可改用其他端口或 taskkill /f /pid %%p 处理
  set /a FAILS+=1
  exit /b 0
)
call :pick_fallback_port
exit /b 0

:pick_fallback_port
REM 从 8001-8019（跳过 8011 语音端口）找第一个空闲端口
set "PICKED="
for /l %%i in (8001,1,8019) do (
  if not defined PICKED if not "%%i"=="8011" (
    netstat -ano | findstr /r /c:":%%i .*LISTENING" >nul 2>nul
    if errorlevel 1 set "PICKED=%%i"
  )
)
if defined PICKED (
  echo   [OK] 后端将改用空闲端口 !PICKED!（学习入口 http://localhost:!PICKED!/）
  set "BACKEND_PORT=!PICKED!"
  exit /b 0
)
echo   [FAIL] 8001-8019（除 8011）也全部被占用，找不到可用后端端口。
set /a FAILS+=1
exit /b 0

:kill_port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%1 .*LISTENING"') do taskkill /f /pid %%p >nul 2>nul
exit /b 0

:wait_http
REM %1=名称 %2=URL %3=最大尝试次数（每次约 2 秒）
set /a WH_N=0
:wait_http_loop
curl -s --fail --max-time 2 -o nul "%~2" >nul 2>nul
if not errorlevel 1 (
  echo   [OK] %~1 就绪
  exit /b 0
)
set /a WH_N+=1
if %WH_N% geq %~3 (
  echo   [FAIL] %~1 未在时限内就绪，请查看对应窗口的报错日志
  exit /b 1
)
ping -n 3 127.0.0.1 >nul
goto wait_http_loop
