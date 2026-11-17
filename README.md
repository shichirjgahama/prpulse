## быстрый старт

```powershell
git clone https://github.com/shichirjgahama/prpulse.git
cd prpulse
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[pdf,test]"

python scripts\prepare_samples.py
python scripts\run_all.py
python -m projectpulse --home .\demo_home gui
run_all.py индексирует два демопроекта и собирает отчёты в reports\. первый запуск занимает несколько минут.
тесты:
python -m unittest discover -s tests
отчёты: reports\pluggy.html, reports\pluggy.pdf, reports\summary.json.
