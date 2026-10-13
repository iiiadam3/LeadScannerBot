@echo off
echo !!! RUNNING FROM BAT FILE !!!

set "GMAIL_APP_PASSWORD=ycehcczwymjfbfsh"
set "DATABASE_URL=postgresql://postgres:Aylin191King2026@db.yxxtefdeowbbnkvdwnlo.supabase.co:5432/postgres"

cd /d "C:\Users\adama\PycharmProjects\RedditScanner"
".venv\Scripts\python.exe" r3ddit.py

pause