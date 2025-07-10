#!/bin/bash

# Проверка наличия двух параметров
if [ $# -ne 2 ]; then
  echo "Использование: $0 <bot_name> <telegram_bot_token>"
  exit 1
fi

# Присваиваем значения параметров
bot_name=$1
telegram_bot_token=$2

# Каталоги
source_dir="/home/server/tg_build_bot/v_2/new_bot_file"
target_dir="/home/server/tg_build_bot/bots/$bot_name"

# Проверяем наличие исходного каталога
if [ ! -d "$source_dir" ]; then
  echo "Исходная папка $source_dir не найдена!"
  exit 1
fi

# Копируем папку с теми же правами и атрибутами
cp -a "$source_dir" "$target_dir"
if [ $? -ne 0 ]; then
  echo "Ошибка при копировании папки!"
  exit 1
fi

echo "Папка скопирована и переименована в $target_dir с сохранением прав"

# Меняем права доступа для новой директории и всех её файлов
sudo chmod -R 777 "$target_dir"
if [ $? -ne 0 ]; then
  echo "Ошибка при изменении прав доступа!"
  exit 1
fi

echo "Права доступа для $target_dir изменены на 777 (доступно для всех пользователей)"


# Переходим в новую папку
cd "$target_dir" || exit 1

# Исходный конфиг файл
conf_file="supervisor.conf"

# Проверяем наличие supervisor.conf в новой папке
if [ ! -f "$conf_file" ]; then
  echo "Файл $conf_file не найден в папке $target_dir!"
  exit 1
fi

# Создаем новый конфиг с замененным bot_name
new_conf_file="${bot_name}.conf"
sed "s/_bot_name/$bot_name/g" "$conf_file" > "$new_conf_file"

# Копируем новый конфиг в /etc/supervisor/conf.d
sudo cp "$new_conf_file" /etc/supervisor/conf.d/

# Проверяем наличие settings.json в новой папке
settings_file="settings.json"
if [ ! -f "$settings_file" ]; then
  echo "Файл $settings_file не найден в папке $target_dir!"
  exit 1
fi

# Обновляем значение TELEGRAM_BOT_TOKEN в settings.json
jq --arg token "$telegram_bot_token" '.TELEGRAM_BOT_TOKEN = $token' "$settings_file" > tmp_settings.json && mv tmp_settings.json "$settings_file"

chmod 777 "$settings_file"

# Проверяем результат замены
if [ $? -eq 0 ]; then
  echo "Конфиг $new_conf_file создан и скопирован в /etc/supervisor/conf.d/"
  echo "TELEGRAM_BOT_TOKEN обновлен в settings.json"
else
  echo "Ошибка при обновлении settings.json"
  exit 1
fi

# Рестартуем supervisor для применения изменений
sudo supervisorctl reread
sudo supervisorctl update

echo "Все готово!"

# Изменяем права доступа для новой директории и её содержимого
sudo chmod -R 777 "$target_dir"
if [ $? -eq 0 ]; then
  echo "Права доступа для $target_dir успешно изменены на 777"
else
  echo "Ошибка при изменении прав доступа для $target_dir"
  exit 1
fi