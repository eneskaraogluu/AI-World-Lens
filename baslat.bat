@echo off
title AI World Lens - Baslatici
echo ==============================================
echo AI World Lens - Arastirma Paneli Baslatiliyor...
echo ==============================================
echo.

if not exist "%~dp0venv\Scripts\python.exe" (
    echo HATA: Sanal ortam bulunamadi. Once README.md icindeki kurulum adimlarini uygulayin.
    pause
    exit /b 1
)

if not exist "%~dp0.env" (
    echo HATA: .env bulunamadi. .env.example dosyasini .env olarak kopyalayip API anahtarlarini girin.
    pause
    exit /b 1
)

echo [1/2] Arka Plan Sunucusu (Backend) Calistiriliyor...
start "AI World Lens - Backend (KAPATMAYIN)" cmd /k "cd /d %~dp0 && .\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000"

echo [2/2] Arayuz Sunucusu (Frontend) Calistiriliyor...
start "AI World Lens - Frontend (KAPATMAYIN)" cmd /k "cd /d %~dp0\frontend && ..\venv\Scripts\python.exe -m http.server 3000"

echo.
echo Her sey hazir! Tarayicinizda proje aciliyor...
timeout /t 3 /nobreak > nul
start http://localhost:3000

echo.
echo NOT: Arka planda acilan 2 adet siyah CMD penceresini proje calistigi surece kapatmayin!
echo Uygulamayi durdurmak istediginizde o pencereleri carpidan kapatabilirsiniz.
pause
