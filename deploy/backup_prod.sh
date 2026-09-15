#!/usr/bin/env bash
#
# Снимок production перед выкладкой: база, версия кода, состояние процессов.
# Запускать НА СЕРВЕРЕ под root, до git pull и до перезапуска сервисов.
#
#   bash deploy/backup_prod.sh
#
# Восстановление — deploy/rollback_prod.sh, инструкция целиком — deploy/RUNBOOK.md.
set -euo pipefail

BASE_DIR=${BASE_DIR:-/home/VodkaBot}
DB_PATH="$BASE_DIR/tg_base.sqlite"
REPO_DIR="$BASE_DIR/vodka_bot"
STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BASE_DIR/backups/$STAMP"

echo "== Бэкап production =="
echo "Каталог: $DEST"
mkdir -p "$DEST"

# --- База ---------------------------------------------------------------------
# Именно .backup, а не cp: файл открыт тремя работающими процессами, и обычное
# копирование может застать базу в середине транзакции. .backup делает
# согласованный снимок, останавливать сервисы для него не нужно.
echo "-- база данных"
sqlite3 "$DB_PATH" ".backup '$DEST/tg_base.sqlite'"
sqlite3 "$DEST/tg_base.sqlite" "PRAGMA integrity_check;" | head -1
ls -lh "$DEST/tg_base.sqlite" | awk '{print "   размер:", $5}'

# Счётчики строк — по ним после выкладки видно, что ничего не потерялось.
echo "-- счётчики строк"
sqlite3 "$DEST/tg_base.sqlite" "
  SELECT 'receipts', count(*) FROM receipts
  UNION ALL SELECT 'receipt_items', count(*) FROM receipt_items
  UNION ALL SELECT 'participant_messages', count(*) FROM participant_messages
  UNION ALL SELECT 'prize_draw_stages', count(*) FROM prize_draw_stages
  UNION ALL SELECT 'prize_draw_rules', count(*) FROM prize_draw_rules
  UNION ALL SELECT 'prize_draw_winners', count(*) FROM prize_draw_winners
  UNION ALL SELECT 'users', count(*) FROM users;
" | tee "$DEST/row_counts_before.txt"

# Прогресс участников активного этапа: после выкладки числа должны совпасть.
sqlite3 "$DEST/tg_base.sqlite" "
  SELECT r.user_tg_id, sum(ri.quantity)
  FROM receipt_items ri JOIN receipts r ON r.id = ri.receipt_id
  JOIN prize_draw_rules pr ON pr.id = ri.matched_rule_id
  JOIN prize_draw_stages s ON s.id = pr.stage_id AND s.status = 'active'
  WHERE r.status = 'Подтверждён'
  GROUP BY r.user_tg_id ORDER BY r.user_tg_id;
" > "$DEST/active_stage_progress_before.txt"
echo "   прогресс участников сохранён в active_stage_progress_before.txt"

# --- Код ----------------------------------------------------------------------
echo "-- версия кода"
git -C "$REPO_DIR" rev-parse HEAD > "$DEST/git_head.txt"
git -C "$REPO_DIR" status --porcelain > "$DEST/git_status.txt"
# Незакоммиченные правки на сервере (например, старый локальный патч site_bot/main.py)
git -C "$REPO_DIR" diff > "$DEST/git_uncommitted.diff" || true
echo "   HEAD: $(cat "$DEST/git_head.txt")"
if [ -s "$DEST/git_status.txt" ]; then
  echo "   ВНИМАНИЕ: на сервере есть незакоммиченные изменения, см. git_status.txt"
fi

# --- Конфигурация -------------------------------------------------------------
echo "-- конфигурация и состояние"
cp "$BASE_DIR/settings.json" "$DEST/settings.json" 2>/dev/null || true
cp /etc/supervisor/conf.d/vodka_services.conf "$DEST/vodka_services.conf" 2>/dev/null || true
supervisorctl status > "$DEST/supervisor_status.txt" 2>&1 || true

echo
echo "Готово: $DEST"
echo "Откат: bash deploy/rollback_prod.sh $STAMP"
