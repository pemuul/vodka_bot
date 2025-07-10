#!/bin/bash

# Проверка наличия одного параметра (названия бота)
if [ $# -ne 1 ]; then
  echo "Использование: $0 <bot_name>"
  exit 1
fi

# Присваиваем значение параметра
bot_name=$1

# Пути
supervisor_conf_dir="/etc/supervisor/conf.d"
bot_conf_file="$supervisor_conf_dir/${bot_name}.conf"
bot_dir="/home/server/tg_build_bot/bots/$bot_name"

# Остановка процесса в supervisorctl по названию бота
echo "Останавливаем процесс $bot_name в Supervisor..."
sudo supervisorctl stop "$bot_name"
if [ $? -ne 0 ]; then
  echo "Ошибка при остановке процесса $bot_name. Возможно, процесс уже остановлен или не существует."
fi

# Удаление конфигурационного файла Supervisor
if [ -f "$bot_conf_file" ]; then
  echo "Удаляем конфигурационный файл $bot_conf_file..."
  sudo rm "$bot_conf_file"
  if [ $? -ne 0 ]; then
    echo "Ошибка при удалении конфигурационного файла $bot_conf_file"
    exit 1
  fi
else
  echo "Файл конфигурации $bot_conf_file не найден!"
fi

# Удаление директории бота
if [ -d "$bot_dir" ]; then
  echo "Удаляем папку бота $bot_dir..."
  sudo rm -rf "$bot_dir"
  if [ $? -ne 0 ]; then
    echo "Ошибка при удалении папки $bot_dir"
    exit 1
  fi
else
  echo "Папка бота $bot_dir не найдена!"
fi

# Обновление конфигурации Supervisor
echo "Обновляем конфигурацию Supervisor..."
sudo supervisorctl reread
sudo supervisorctl update

echo "Процесс удаления завершен!"
