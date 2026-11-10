#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
import time
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from openpyxl.utils import get_column_letter
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


MAX_REELS = 9
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._]{1,30}$")
RESERVED = {
    "p", "reel", "reels", "stories", "explore",
    "accounts", "direct", "about", "developer"
}


def log(message):
    print(message, flush=True)


def normalize_username(value):
    if value is None:
        return None

    value = str(value).strip().strip(" \t\r\n,;\"'()[]{}<>")

    if not value or value.lower() in ("nan", "none", "null"):
        return None

    match = re.search(
        r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})",
        value,
        re.I
    )

    if match:
        username = match.group(1)
    else:
        username = value.lstrip("@").split("/")[0].split("?")[0]

    username = username.lower()

    if USERNAME_RE.fullmatch(username) and username not in RESERVED:
        return username

    return None


def read_input(path):
    path = Path(path).expanduser()

    if not path.is_file():
        raise FileNotFoundError(path)

    raw = path.read_bytes()
    probe = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()

    # HTML, в том числе файл с расширением .xls
    if probe.startswith((b"<html", b"<!doctype html")) or b"<table" in probe:
        for encoding in ("utf-8-sig", "cp1251", "utf-8"):
            try:
                html = raw.decode(encoding)
                tables = pd.read_html(StringIO(html), keep_default_na=False)
                if tables:
                    return tables[0]
            except Exception:
                pass

    # XLSX
    if raw.startswith(b"PK"):
        sheets = pd.read_excel(
            path, sheet_name=None, dtype=str, engine="openpyxl"
        )
        return next(iter(sheets.values()))

    # Настоящий XLS
    if raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        sheets = pd.read_excel(
            path, sheet_name=None, dtype=str, engine="xlrd"
        )
        return next(iter(sheets.values()))

    # CSV
    for encoding in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            return pd.read_csv(
                path, dtype=str, encoding=encoding,
                sep=None, engine="python", keep_default_na=False
            )
        except Exception:
            pass

    raise ValueError("Не удалось определить формат входного файла")


def extract_source(path):
    frame = read_input(path).copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame.fillna("")

    instagram_column = next(
        (c for c in frame.columns if c.lower() == "instagram"),
        None
    )

    if instagram_column is None:
        raise ValueError("В таблице не найдена колонка Instagram")

    usernames = [
        normalize_username(value)
        for value in frame[instagram_column].tolist()
    ]

    return frame, usernames


def parse_datetime(value):
    if not value:
        return None

    try:
        result = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(result):
            return None
        return result.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


def collect_reel_links(page, username):
    url = f"https://www.instagram.com/{username}/reels/"

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    try:
        page.wait_for_selector('a[href*="/reel/"]', timeout=20000)
        hrefs = page.locator('a[href*="/reel/"]').evaluate_all(
            "(els) => els.map(el => el.href)"
        )
    except PlaywrightTimeoutError:
        log("  Сетка Reels не появилась")
        return []

    result = []
    seen = set()

    for href in hrefs:
        try:
            parts = [x for x in urlparse(href).path.split("/") if x]
            index = next(
                i for i, part in enumerate(parts)
                if part in ("reel", "reels")
            )
            shortcode = parts[index + 1]

            if shortcode in seen:
                continue

            seen.add(shortcode)
            result.append(
                f"https://www.instagram.com/{username}/reel/{shortcode}/"
            )

            if len(result) >= MAX_REELS:
                break

        except (StopIteration, IndexError):
            continue

    log(f"  Найдено ссылок: {len(result)}")
    return result


def json_ld_dates(page):
    dates = []
    scripts = page.locator('script[type="application/ld+json"]')

    def walk(obj):
        if isinstance(obj, dict):
            for key in ("uploadDate", "datePublished"):
                value = obj.get(key)
                if isinstance(value, str):
                    dates.append(value)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    for i in range(scripts.count()):
        try:
            walk(json.loads(scripts.nth(i).inner_text()))
        except Exception:
            continue

    return dates


def read_reel_date(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)

        values = []

        try:
            values.extend(
                page.locator("time[datetime]").evaluate_all(
                    "(els) => els.map(el => el.getAttribute('datetime'))"
                )
            )
        except Exception:
            pass

        selectors = [
            'meta[property="article:published_time"]',
            'meta[property="og:published_time"]',
            'meta[name="date"]',
            'meta[name="publish_date"]',
        ]

        for selector in selectors:
            try:
                element = page.locator(selector).first
                if element.count():
                    values.append(element.get_attribute("content"))
            except Exception:
                pass

        values.extend(json_ld_dates(page))

        parsed = [
            dt for value in values
            if (dt := parse_datetime(value)) is not None
        ]

        return max(parsed) if parsed else None

    except Exception as error:
        log(f"    Ошибка открытия Reel: {error}")
        return None


def check_account(page, username, max_days):
    log(f"\nПроверяю @{username}")

    try:
        urls = collect_reel_links(page, username)
    except Exception as error:
        return {
            "username": username, "status": "unknown",
            "date": None, "age_days": None, "reel_url": None,
            "checked": 0, "total": 0, "reason": str(error)
        }

    if not urls:
        return {
            "username": username, "status": "unknown",
            "date": None, "age_days": None, "reel_url": None,
            "checked": 0, "total": 0,
            "reason": "Не удалось получить ссылки на Reels"
        }

    latest = None
    latest_url = None
    failed = False

    for index, url in enumerate(urls, 1):
        log(f"  Reel {index}/{len(urls)}")

        dt = read_reel_date(page, url)

        if dt is None:
            log("    Дата не определена")
            failed = True
            continue

        age = (date.today() - dt.date()).days
        log(f"    Дата: {dt.date()} | возраст: {age} дней")

        if age < 0:
            failed = True
            continue

        if latest is None or dt > latest:
            latest = dt
            latest_url = url

        time.sleep(0.2)

    if latest is None:
        status = "unknown"
        reason = "Не удалось определить дату публикации"
        age_days = None

    else:
        age_days = (date.today() - latest.date()).days

        if age_days <= max_days:
            status = "keep"
            reason = "Найдена свежая публикация"
        elif failed:
            status = "unknown"
            reason = "Не удалось прочитать даты всех проверенных Reels"
        else:
            status = "exclude"
            reason = f"Все проверенные Reels старше {max_days} дней"

    log(f"  Результат: {status.upper()}")

    return {
        "username": username,
        "status": status,
        "date": latest.date() if latest else None,
        "age_days": age_days,
        "reel_url": latest_url,
        "checked": len(urls),
        "total": len(urls),
        "reason": reason
    }


def save_results(source, usernames, results, output_path):
    by_username = {r["username"]: r for r in results}

    output = source.copy()

    if "Дата" not in output.columns:
        output["Дата"] = ""

    if "instagram_username" in output.columns:
        output = output.drop(columns=["instagram_username"])

    statuses = []
    dates = []

    for username in usernames:
        result = by_username.get(username) if username else None

        statuses.append(result["status"] if result else "unknown")

        dates.append(
            result["date"].strftime("%d.%m.%Y")
            if result and result["date"] else ""
        )

    output["Дата"] = dates
    output["instagram_username"] = [u or "" for u in usernames]

    keep = output[[s == "keep" for s in statuses]].copy()
    exclude = output[[s == "exclude" for s in statuses]].copy()
    unknown = output[[s == "unknown" for s in statuses]].copy()

    report = pd.DataFrame(results, columns=[
        "username", "status", "date", "age_days",
        "reel_url", "checked", "total", "reason"
    ])

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        keep.to_excel(writer, sheet_name="Оставить", index=False)
        exclude.to_excel(writer, sheet_name="Исключить", index=False)
        unknown.to_excel(writer, sheet_name="Неизвестно", index=False)
        output.to_excel(writer, sheet_name="Все аккаунты", index=False)
        report.to_excel(writer, sheet_name="Технический отчёт", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions

            for cells in ws.columns:
                letter = get_column_letter(cells[0].column)
                width = max(
                    (len(str(cell.value or "")) for cell in cells),
                    default=10
                )
                ws.column_dimensions[letter].width = min(width + 2, 60)


def main():
    parser = argparse.ArgumentParser(
        description="Проверка последних Instagram Reels"
    )
    parser.add_argument("input", help="Входной XLS/XLSX/CSV/HTML")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", default="instagram_checked.xlsx")
    args = parser.parse_args()

    if args.days < 0:
        parser.error("--days не может быть отрицательным")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit должен быть положительным")

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if input_path == output_path:
        parser.error("Входной и выходной файлы не должны совпадать")

    try:
        source, usernames = extract_source(input_path)
    except Exception as error:
        log(f"Ошибка чтения файла: {error}")
        sys.exit(1)

    unique = list(dict.fromkeys(u for u in usernames if u))

    if not unique:
        log("Instagram-аккаунты не найдены")
        sys.exit(1)

    if args.limit is not None:
        unique = unique[:args.limit]

    allowed = set(unique)
    usernames = [
        u if u in allowed else None
        for u in usernames
    ]

    log(f"Строк в таблице: {len(source)}")
    log(f"Аккаунтов к проверке: {len(unique)}")
    log(f"Порог активности: {args.days} дней")
    log(f"Reels на аккаунт: до {MAX_REELS}")
    log(f"Выходной файл: {output_path}")

    results = []

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(
                Path.home() / ".instagram-reels-checker-profile"
            ),
            headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU"
        )

        try:
            page = context.new_page()

            log("\nОткрываю Instagram")
            page.goto(
                "https://www.instagram.com/",
                wait_until="domcontentloaded",
                timeout=60000
            )

            input("Если нужно, войди в Instagram. Затем нажми Enter здесь... ")

            for index, username in enumerate(unique, 1):
                log(f"\n[{index}/{len(unique)}] @{username}")

                result = check_account(page, username, args.days)
                results.append(result)

                log(
                    f"  Проверено: {result['checked']} | "
                    f"{result['status'].upper()}"
                )
                time.sleep(1)

        finally:
            context.close()

    try:
        save_results(source, usernames, results, output_path)
    except Exception as error:
        log(f"Ошибка сохранения Excel: {error}")
        sys.exit(1)

    for status, label in (
        ("keep", "Оставить"),
        ("exclude", "Исключить"),
        ("unknown", "Неизвестно")
    ):
        log(f"{label}: {sum(r['status'] == status for r in results)}")

    log(f"\nГотово: {output_path}")


if __name__ == "__main__":
    main()
