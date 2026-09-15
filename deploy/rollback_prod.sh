#!/usr/bin/env bash
#
# Откат выкладки. Запускать НА СЕРВЕРЕ под root:
#
#   bash deploy/rollback_prod.sh 20260915_120000        # код + база
#   ROLLBACK_DB=0 bash deploy/rollback_prod.sh 20260915_120000   # только код
#
# По умолчанию откатывается И код, И база. Чаще всего база не нужна: миграция только
# ДОБАВЛЯЕТ две колонки и индекс, старый код их просто не замечает — поэтому откат одного
# кода безопасен и не теряет сообщения, накопившиеся после выкладки. Базу восстанавливайте
# только если данные реально пострадали: всё, что пользователи прислали после бэкапа, при
# этом пропадёт.
set -euo pipefail

STAMP=${1:-}
if [ -z "$STAMP" ]; then
  echo "Укажите метку бэкапа, например: bash deploy/rollback_prod.sh 20260915_120000" >&2
  echo "Доступные:" >&2
  ls -1 "${BASE_DIR:-/home/VodkaBot}/backups" >&2 || true
  exit 1
fi

BASE_DIR=${BASE_DIR:-/home/VodkaBot}
REPO_DIR="$BASE_DIR/vodka_bot"
SRC="$BASE_DIR/backups/$STAMP"
ROLLBACK_DB=${ROLLBACK_DB:-1}

[ -d "$SRC" ] || { echo "Нет каталога бэкапа: $SRC" >&2; exit 1; }

echo "== Откат на $STAMP =="
supervisorctl stop vodka_bot vodka_bot_check vodka_site

echo "-- код"
git -C "$REPO_DIR" checkout "$(cat "$SRC/git_head.txt")"

if [ "$ROLLBACK_DB" = "1" ]; then
  echo "-- база"
  SAFETY="$BASE_DIR/backups/${STAMP}_before_rollback.sqlite"
  sqlite3 "$BASE_DIR/tg_base.sqlite" ".backup '$SAFETY'"
  echo "   текущая база сохранена в $SAFETY"
  cp "$SRC/tg_base.sqlite" "$BASE_DIR/tg_base.sqlite"
  chown root:root "$BASE_DIR/tg_base.sqlite"
else
  echo "-- база не трогается (ROLLBACK_DB=0)"
fi

supervisorctl start vodka_bot vodka_bot_check vodka_site
sleep 3
supervisorctl status
