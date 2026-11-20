@echo off
setlocal EnableDelayedExpansion
REM ===========================================================================
REM  Wave 0 parallel-worktree helper (TASK-0064)
REM  Usage: worktree.bat <lane-name>
REM  Creates an isolated git worktree + branch for one parallel lane,
REM  based on the latest main. Each session works in its own directory,
REM  so multi-session edits never collide in the main workspace.
REM
REM  Known lanes (from docs/MASTER_PLAN.md):
REM    v2.2-a1        lane A - zero-beginner A1 path
REM    v2.3-content   lane B - content factory
REM    v3.2-pron      lane C - pronunciation coach
REM    v3.0-daily     lane A - daily path + gamification
REM    v3.1-listen    lane B - listening
REM    v3.3-grammar   lane B - grammar microcards
REM    v4.0-speaking  lane A - speaking assessment
REM    v4.1-mobile    lane D - mobile + deployment
REM  Any other <lane-name> is accepted verbatim as branch/worktree suffix.
REM ===========================================================================

cd /d "%~dp0"
set "LANE=%~1"
if "%LANE%"=="" goto :usage

set "BRANCH=feature/%LANE%"
REM 脚本在 scripts/ 下运行：..\.. 才是 tool_box 根，worktree 放仓库外避免污染主仓
set "WTROOT=..\..\_worktrees"
set "WTDIR=%WTROOT%\%LANE%"

echo.
echo [worktree] lane      : %LANE%
echo [worktree] branch    : %BRANCH%
echo [worktree] directory : %WTDIR%
echo.

REM --- refuse if branch already exists ---
git show-ref --verify --quiet "refs/heads/%BRANCH%"
if not errorlevel 1 (
  echo [ERROR] branch %BRANCH% already exists. Pick a different lane name.
  exit /b 1
)

REM --- refuse if target dir already exists ---
if exist "%WTDIR%" (
  echo [ERROR] directory %WTDIR% already exists. Remove it first or pick another lane.
  exit /b 1
)

REM --- make sure main is up to date locally (no auto-pull: user controls sync) ---
git rev-parse --verify --quiet main >nul
if errorlevel 1 (
  echo [ERROR] local branch 'main' not found. Cannot base worktree on it.
  exit /b 1
)

if not exist "%WTROOT%" mkdir "%WTROOT%"

git worktree add -b "%BRANCH%" "%WTDIR%" main
if errorlevel 1 (
  echo [ERROR] git worktree add failed. See message above.
  exit /b 1
)

echo.
echo [worktree] OK. Work in: %WTDIR%
echo [worktree] When done, from main repo run:
echo   git worktree remove "%WTDIR%"
echo   then merge %BRANCH% into main at the integration gate.
exit /b 0

:usage
echo Usage: worktree.bat ^<lane-name^>
echo Example: worktree.bat v2.2-a1
echo Run with no argument to list this help.
exit /b 1
