@echo off
cd /d "%~dp0"
if not exist "app_csv_suite_final_geo.py" (
  echo ❌ Brak app_csv_suite_final_geo.py
  pause
  exit /b
)
python -m pip install --quiet --upgrade pip
python -m pip install --quiet streamlit pandas requests charset-normalizer
echo ✅ Startuje aplikacje OBRÓBKA CSV...
streamlit run app_csv_suite_final_geo.py
pause
