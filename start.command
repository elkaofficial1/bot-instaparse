#!/bin/bash

cd "$(dirname "$0")"
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
CHECKER="$ROOT/instagram_reels_checker.py"

clear
echo "======================================"
echo "       INSTAGRAM REELS CHECKER"
echo "======================================"
echo
echo "Папка с исходными файлами: xls/"
echo "Папка с результатами:      results/"
echo

while true; do
    echo
    echo "--------------------------------------"
    echo "1. Начать проверку"
    echo "2. Закрыть программу"
    echo "--------------------------------------"
    read -r -p "Выбери действие: " choice

    case "$choice" in
        1)
            files=()

            while IFS= read -r -d '' file; do
                files+=("$file")
            done < <(
                find "$ROOT/xls" -maxdepth 1 -type f \
                \( -iname '*.xls' -o -iname '*.xlsx' \
                -o -iname '*.ods' -o -iname '*.csv' \
                -o -iname '*.html' -o -iname '*.htm' \) \
                -print0 | sort -z
            )

            if [ ${#files[@]} -eq 0 ]; then
                echo
                echo "В папке xls нет подходящих файлов."
                read -r -p "Нажми Enter..."
                continue
            fi

            echo
            echo "Найдено файлов: ${#files[@]}"
            echo

            for file in "${files[@]}"; do
                name="$(basename "$file")"
                base="${name%.*}"
                output="$ROOT/results/${base}_checked.xlsx"
                temporary=""

                echo
                echo "======================================"
                echo "Файл: $name"
                echo "======================================"

                input_file="$file"

                # ODS временно преобразуем в CSV
                if [[ "$file" == *.ods || "$file" == *.ODS ]]; then
                    temporary="$(mktemp -t instagram-ods).csv"

                    "$PY" - "$file" "$temporary" <<'PY'
import sys
import pandas as pd

df = pd.read_excel(sys.argv[1], engine="odf", dtype=str)
df.to_csv(sys.argv[2], index=False)
PY

                    input_file="$temporary"
                fi

                "$PY" "$CHECKER" "$input_file" \
                    --days 30 \
                    --output "$output"

                result=$?

                if [ -n "$temporary" ]; then
                    rm -f "$temporary"
                fi

                if [ "$result" -eq 0 ]; then
                    # Форматируем даты в Excel
                    "$PY" - "$output" <<'PY'
import sys
from openpyxl import load_workbook
from datetime import date, datetime

path = sys.argv[1]
wb = load_workbook(path)

for ws in wb.worksheets:
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, (date, datetime)):
                cell.number_format = "DD.MM.YYYY"

wb.save(path)
PY
                    echo
                    echo "ГОТОВО: $output"
                else
                    echo
                    echo "ОШИБКА обработки: $name"
                fi
            done

            echo
            echo "======================================"
            echo "Обработка всех файлов завершена."
            echo "Результаты находятся в results/"
            echo "======================================"
            read -r -p "Нажми Enter для возврата в меню..."
            clear
            ;;
        2)
            echo "До встречи!"
            exit 0
            ;;
        *)
            echo "Неизвестная команда."
            ;;
    esac
done
