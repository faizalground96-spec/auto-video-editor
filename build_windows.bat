@echo off
REM build_windows.bat — Build Auto Video Editor di Windows (Tahap 10).
REM Semua keluaran dicatat ke build.log. Tahan terhadap folder berspasi.
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "LOG=%ROOT%build.log"
set "VENV=%ROOT%.venv-win"
set "BIN=%ROOT%bin"

echo === Build dimulai: %DATE% %TIME% === > "%LOG%"
call :log "ROOT=%ROOT%"

REM --- 1. cek Python -------------------------------------------------------
call :log "--- Cek Python ---"
py -3.11 --version >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3.11"
    call :log "Python: py -3.11"
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL%==0 (
        set "PY=python"
        call :log "Python: python (fallback)"
    ) else (
        call :log "GALAT: Python 3.11 tidak ditemukan."
        echo GALAT: Python 3.11 tidak ditemukan. Pasang dari python.org. | tee -a "%LOG%"
        exit /b 1
    )
)

REM --- 2. venv + requirements ----------------------------------------------
call :log "--- venv + pip install ---"
if not exist "%VENV%\Scripts\python.exe" (
    call :log "Membuat venv..."
    %PY% -m venv "%VENV%" >> "%LOG%" 2>&1
    if %ERRORLEVEL% neq 0 (
        echo GALAT: gagal membuat venv. Lihat build.log. | tee -a "%LOG%"
        exit /b 1
    )
)
call :log "pip install -r requirements.txt ..."
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%VENV%\Scripts\python.exe" -m pip install -r "%ROOT%requirements.txt" >> "%LOG%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo GALAT: pip install gagal. Lihat build.log. | tee -a "%LOG%"
    exit /b 1
)

REM --- 3. ffmpeg.exe --------------------------------------------------------
call :log "--- ffmpeg ---"
if not exist "%BIN%\ffmpeg.exe" (
    call :log "ffmpeg.exe belum ada, mengunduh..."
    mkdir "%BIN%" 2>nul
    set "FFURL="
    set "FFSHA="
    for /f "usebackq delims=" %%L in ("%ROOT%tools\ffmpeg_win.txt") do (
        set "LINE=%%L"
        if "!LINE:~0,1!" neq "#" if "!LINE!" neq "" (
            if "!FFURL!"=="" ( set "FFURL=!LINE!" ) else ( set "FFSHA=!LINE!" )
        )
    )
    call :log "URL: !FFURL!"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '!FFURL!' -OutFile '%ROOT%ffmpeg_dl.zip'" >> "%LOG%" 2>&1
    if %ERRORLEVEL% neq 0 (
        call :log "GALAT: unduhan ffmpeg gagal."
        echo. | tee -a "%LOG%"
        echo GALAT: unduhan ffmpeg gagal. | tee -a "%LOG%"
        echo Silakan unduh manual dari https://www.gyan.dev/ffmpeg/builds/ | tee -a "%LOG%"
        echo lalu letakkan ffmpeg.exe di: "%BIN%\ffmpeg.exe" | tee -a "%LOG%"
        exit /b 1
    )
    if not "!FFSHA!"=="" (
        call :log "Verifikasi SHA256..."
        for /f %%H in ('powershell -NoProfile -Command "(Get-FileHash '%ROOT%ffmpeg_dl.zip' -Algorithm SHA256).Hash.ToLower()"') do set "GOT=%%H"
        if /i not "!GOT!"=="!FFSHA!" (
            call :log "GALAT: SHA256 tidak cocok."
            echo GALAT: SHA256 ffmpeg tidak cocok. Hapus ffmpeg_dl.zip dan coba lagi. | tee -a "%LOG%"
            exit /b 1
        )
        call :log "SHA256 cocok."
    ) else (
        call :log "PERINGATAN: SHA256 tidak diisi di tools\ffmpeg_win.txt, lewati verifikasi."
    )
    powershell -NoProfile -Command "Expand-Archive -Path '%ROOT%ffmpeg_dl.zip' -DestinationPath '%ROOT%ffmpeg_tmp' -Force" >> "%LOG%" 2>&1
    for /r "%ROOT%ffmpeg_tmp" %%F in (ffmpeg.exe) do (
        copy "%%F" "%BIN%\ffmpeg.exe" >> "%LOG%" 2>&1
        goto :ffdone
    )
    :ffdone
    rmdir /s /q "%ROOT%ffmpeg_tmp" 2>nul
    del "%ROOT%ffmpeg_dl.zip" 2>nul
    if not exist "%BIN%\ffmpeg.exe" (
        echo GALAT: ffmpeg.exe tak ketemu di arsip. | tee -a "%LOG%"
        exit /b 1
    )
    call :log "ffmpeg.exe siap."
) else (
    call :log "ffmpeg.exe sudah ada."
)

REM --- 4. pyinstaller --------------------------------------------------------
call :log "--- pyinstaller ---"
"%VENV%\Scripts\python.exe" -m PyInstaller --version >> "%LOG%" 2>&1
"%VENV%\Scripts\pyinstaller.exe" "%ROOT%build.spec" --noconfirm >> "%LOG%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo GALAT: pyinstaller gagal. Lihat build.log. | tee -a "%LOG%"
    exit /b 1
)

REM --- 5. self-test hasil build ----------------------------------------------
call :log "--- self-test ---"
set "CLIEXE=%ROOT%dist\AutoVideoEditor\AutoVideoEditorCLI.exe"
if not exist "%CLIEXE%" (
    echo GALAT: %CLIEXE% tidak ada. | tee -a "%LOG%"
    exit /b 1
)
"%CLIEXE%" --self-test >> "%LOG%" 2>&1
set "ST=%ERRORLEVEL%"
type "%LOG%" | findstr /c:"[OK]" /c:"[GAGAL]" /c:"SELF-TEST"
if %ST% neq 0 (
    echo. | tee -a "%LOG%"
    echo PERINGATAN: self-test GAGAL — build bermasalah. Lihat build.log. | tee -a "%LOG%"
    exit /b 1
)

echo. | tee -a "%LOG%"
echo BUILD SELESAI: dist\AutoVideoEditor\ | tee -a "%LOG%"
exit /b 0

:log
echo %~1 >> "%LOG%"
echo %~1
goto :eof
