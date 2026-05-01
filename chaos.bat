@echo off
rem Windows wrapper for chaos.py — call via `chaos <subcommand>` from any
rem cmd / PowerShell session that has the repo root on PATH (or just from
rem the repo root directly).
python "%~dp0chaos.py" %*
