@echo off
chcp 65001 > nul

set "TARGET_DIR=D:\claudeAgent\CWBuilder"
set "REPO_URL=https://github.com/igalvadim-debug/CWBuilder.git"

if exist "%TARGET_DIR%\.git" (
    cd /d "%TARGET_DIR%"
    git pull
) else (
    if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
    git clone %REPO_URL% "%TARGET_DIR%"
)
