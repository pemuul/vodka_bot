import paramiko
import os
from scp import SCPClient

# Функция для получения списка файлов и папок в локальной папке
def get_files_and_folders(path, exclude_item):
    items = []
    for item in os.listdir(path):
        if item != exclude_item:
            items.append(os.path.join(path, item))
    return items

# Функция для рекурсивной копии файлов и папок на удаленный сервер
def copy_files_recursive(scp, local_path, remote_path, exclude_item):
    for item in get_files_and_folders(local_path, exclude_item):
        print(item)
        if os.path.isfile(item):
            scp.put(item, remote_path)
        elif os.path.isdir(item):
            remote_subfolder = os.path.join(remote_path, os.path.basename(item))
            scp.put(item, recursive=True, remote_path=remote_subfolder)
            copy_files_recursive(scp, item, remote_subfolder, exclude_item)

def upload_folder(host, port, username, password, local_folder, remote_path, command):
    #try:
    # Создаем клиент SSH
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Подключаемся к серверу
    client.connect(hostname=host, port=port, username=username, password=password)
    stdin, stdout, stderr = client.exec_command(f"sudo -S rm -r /home/server/tg_build_bot/information_telegram_bot")
    # Передаем пароль
    #stdin, stdout, stderr = client.exec_command(f"sudo ls")
    stdin.write(password + '\n')
    stdin.flush()

    output = stdout.read().decode()
    errors = stderr.read().decode()
    print('Output:', output)
    print('Errors:', errors)

    # Создаем экземпляр SCPClient
    with SCPClient(client.get_transport()) as scp:
        # Загружаем локальную папку на сервер, заменяя существующую
        scp.put(local_folder, recursive=True, remote_path=remote_path)
        # отправляем файлы бота
        copy_files_recursive(scp, '../', remote_path+'/bots/test_bots', 'information_telegram_bot')

    print(f"Папка {local_folder} успешно передана на сервер по пути {remote_path}")

    # Выполняем команду с sudo
    stdin, stdout, stderr = client.exec_command(f"sudo -S {command}")
    # Передаем пароль
    #stdin, stdout, stderr = client.exec_command(f"sudo ls")
    stdin.write(password + '\n')
    stdin.flush()

    output = stdout.read().decode()
    errors = stderr.read().decode()
    print('Output:', output)
    print('Errors:', errors)

    # Выводим результат выполнения команды
    for line in stdout:
        print(line)
        print(line.strip())

    # Закрываем соединение
    client.close()

    #except Exception as e:
    #    print(f"Ошибка: {e}")

if __name__ == "__main__":
    # Параметры сервера
    host = "80.78.243.187"
    port = 22  # Порт SSH
    username = "server"
    password = "serverqwe123"

    # Локальная папка, которую нужно передать
    local_folder = "../information_telegram_bot"

    # Путь на сервере, куда нужно передать папку
    remote_path = "/home/server/tg_build_bot"

    # Команда для выполнения под sudo
    command = "supervisorctl reload"

    # Вызываем функцию для загрузки папки и выполнения команды
    upload_folder(host, port, username, password, local_folder, remote_path, command)
