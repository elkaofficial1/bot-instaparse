#!/usr/bin/env bash
set -Eeuo pipefail

REPO="https://github.com/elkaofficial1/bot-instaparse/archive/refs/heads/main.tar.gz"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/InstagramReelsChecker"

log() { printf '\n[INSTALL] %s\n' "$1"; }
fail() { echo "[ERROR] $1" >&2; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip curl
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip curl
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --needed python python-pip curl
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3 python3-pip curl
    else
        fail "Установите Python 3 и curl вручную."
    fi
fi

command -v curl >/dev/null 2>&1 || fail "Не найден curl."
python3 -c 'import venv' 2>/dev/null || fail "Не найден модуль venv для Python."

mkdir -p "$(dirname "$APP_DIR")"

if [[ ! -f "$APP_DIR/launcher.py" ]]; then
    log "Скачиваю проект..."
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    curl -fL "$REPO" -o "$TMP_DIR/project.tar.gz"
    mkdir "$TMP_DIR/extracted"
    tar -xzf "$TMP_DIR/project.tar.gz" -C "$TMP_DIR/extracted"

    SOURCE_DIR="$(find "$TMP_DIR/extracted" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    [[ -f "$SOURCE_DIR/launcher.py" ]] || fail "launcher.py не найден."

    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR"
    cp -a "$SOURCE_DIR/." "$APP_DIR/"
fi

cd "$APP_DIR"
mkdir -p xls results

log "Создаю виртуальное окружение..."
[[ -x .venv/bin/python ]] || python3 -m venv .venv

VENV_PYTHON="$APP_DIR/.venv/bin/python"

log "Устанавливаю зависимости..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

log "Устанавливаю Chromium..."
"$VENV_PYTHON" -m playwright install chromium

if command -v apt-get >/dev/null 2>&1; then
    log "Устанавливаю системные зависимости Chromium..."
    sudo "$VENV_PYTHON" -m playwright install-deps chromium
fi

cat > "$APP_DIR/start.sh" <<EOF
#!/usr/bin/env bash
cd "$APP_DIR"
exec "$VENV_PYTHON" "$APP_DIR/launcher.py"
EOF
chmod +x "$APP_DIR/start.sh"

if [[ "$(uname -s)" == "Linux" ]]; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    [[ -n "$DESKTOP_DIR" ]] || DESKTOP_DIR="$HOME/Desktop"
    mkdir -p "$DESKTOP_DIR" "$HOME/.local/share/applications"

    cat > "$HOME/.local/share/applications/InstagramReelsChecker.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Instagram Reels Checker
Comment=Instagram Reels Checker
Exec="$APP_DIR/start.sh"
Path=$APP_DIR
Terminal=true
Categories=Network;Utility;
EOF

    chmod +x "$HOME/.local/share/applications/InstagramReelsChecker.desktop"
    cp "$HOME/.local/share/applications/InstagramReelsChecker.desktop" "$DESKTOP_DIR/"
    chmod +x "$DESKTOP_DIR/InstagramReelsChecker.desktop"
fi

log "Установка завершена!"
echo "Запуск: $APP_DIR/start.sh"
