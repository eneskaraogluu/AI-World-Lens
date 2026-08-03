@echo off
title AI World Lens - Akademik Rapor Uretici
echo ==============================================
echo Akademik Rapor Uretici Baslatiliyor...
echo ==============================================
echo.
echo Uyari: Bu islem 30 meslek x 10 gorsel = Toplam 300 gorsel uretir.
echo Ortalama sure: 30 - 45 Dakika. Lutfen islem bitene kadar pencereyi kapatmayin!
echo.
pause

cd /d %~dp0
.\venv\Scripts\activate && python run_full_report.py

echo.
pause
