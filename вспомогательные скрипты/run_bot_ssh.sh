#!/bin/sh

# Проверка на количество аргументов
if [ "$#" -ne 3 ]; then
    echo "Использование: $0 <путь_к_питон_файлу> <название_файла> <путь_к_python>"
    exit 1
fi

# Получение аргументов
PYTHON_FILE_PATH="$1"
PYTHON_FILE_NAME="$2"
PYTHON_PATH="$3"

# Проверка на существование файла
if [ ! -f "${PYTHON_FILE_PATH}/${PYTHON_FILE_NAME}" ]; then
    echo "Файл ${PYTHON_FILE_PATH}/${PYTHON_FILE_NAME} не найден."
    exit 1
fi

# Переход в директорию
cd "${PYTHON_FILE_PATH}" || exit

# Запуск python файла и запись PID
(
    # Запуск процесса
    "${PYTHON_PATH}" "${PYTHON_FILE_NAME}" &
    # Получение PID
    echo $! > "pid.txt"
    wait $!
) &

# Печать процесса в терминал
tail -f /dev/null
