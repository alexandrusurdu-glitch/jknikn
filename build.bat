@echo off
REM Construieste executabilul Windows local (necesita Python 3.10+ instalat).
cd /d "%~dp0"
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name PDFTranslatorRO ^
  --icon resources\icon.ico ^
  --add-data "resources;resources" ^
  --collect-all deep_translator --collect-all deepl --collect-all anthropic --collect-data docx ^
  main.py
echo.
echo Executabilul se afla in: dist\PDFTranslatorRO.exe
pause
