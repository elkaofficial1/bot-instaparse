from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
CHECKER = ROOT / "instagram_reels_checker.py"
INPUT = ROOT / "xls"
OUTPUT = ROOT / "results"

def create_shortcut():
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)

    shortcut = desktop / "Instagram Checker.command"
    shortcut.write_text(
        '#!/bin/bash\n'
        f'cd "{ROOT}"\n'
        f'"{PYTHON}" "{ROOT / "launcher.py"}"\n',
        encoding="utf-8"
    )
    shortcut.chmod(0o755)
    print(f"Ярлык создан: {shortcut}")

def get_files():
    extensions = {".xls", ".xlsx", ".ods", ".csv", ".html", ".htm"}
    INPUT.mkdir(exist_ok=True)
    return sorted(
        p for p in INPUT.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    )

def process_file(file):
    output = OUTPUT / f"{file.stem}_checked.xlsx"
    temporary = None
    source = file

    print(f"\n{'=' * 45}\nФайл: {file.name}\n{'=' * 45}")

    try:
        if file.suffix.lower() == ".ods":
            import pandas as pd
            temporary = ROOT / f".temporary_{file.stem}.xlsx"
            pd.read_excel(file, engine="odf", dtype=str).to_excel(
                temporary, index=False
            )
            source = temporary

        subprocess.run([
            str(PYTHON), str(CHECKER), str(source),
            "--days", "30", "--output", str(output)
        ], check=True)

        print(f"\nГотово: {output}")

    except subprocess.CalledProcessError:
        print(f"\nОшибка обработки: {file.name}")
    except Exception as error:
        print(f"\nОшибка: {error}")
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

def main():
    INPUT.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    create_shortcut()

    while True:
        files = get_files()

        print("\n" + "=" * 45)
        print("       INSTAGRAM REELS CHECKER")
        print("=" * 45)
        print(f"\nФайлов в папке xls: {len(files)}")
        print("\n1. Начать проверку")
        print("2. Закрыть программу")

        choice = input("\nВыбери действие: ").strip()

        if choice == "1":
            files = get_files()

            if not files:
                print("\nПапка xls пуста.")
                input("Enter для продолжения...")
                continue

            print(f"\nБудет обработано файлов: {len(files)}")

            for index, file in enumerate(files, 1):
                print(f"\nФайл {index}/{len(files)}")
                process_file(file)

            print("\nВсе файлы обработаны.")
            input("Enter для возврата в меню...")

        elif choice == "2":
            print("До встречи!")
            break

        else:
            print("Неизвестная команда.")

if __name__ == "__main__":
    if not CHECKER.exists():
        print("Не найден instagram_reels_checker.py")
        sys.exit(1)
    main()
