import paramiko
import os
from scp import SCPClient
import datetime

def save_datetime_to_file(file_path):
    current_datetime = datetime.datetime.now()
    with open(file_path, 'w') as file:
        file.write(str(current_datetime))

def read_datetime_from_file(file_path):
    with open(file_path, 'r') as file:
        datetime_str = file.readline().strip()
        return datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S.%f')

# Функция для получения списка файлов и папок в локальной папке
def get_files_and_folders(path, exclude_item):
    items = []
    for item in os.listdir(path):
        if not item in exclude_item:
            #if datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(path, item))) > saved_datetime:
            items.append(os.path.join(path, item))
        #print('- path -> ', path, item)
    return items

# Функция для рекурсивной копии файлов и папок на удаленный сервер
def copy_files_recursive(scp, local_path, remote_path, exclude_item, is_fromtimestamp=True):
    for item in get_files_and_folders(local_path, exclude_item):
        if os.path.isfile(item):
            # Проверяем, что время изменения файла меньше сегодняшнего утра
            file_mtime = os.path.getmtime(item)
            send_file = True
            if is_fromtimestamp:
                send_file = datetime.datetime.fromtimestamp(file_mtime) > saved_datetime
            
            if send_file:
                print(item)
                scp.put(item, remote_path)

            #print('--> ', item)

            #print(datetime.datetime.fromtimestamp(file_mtime), saved_datetime)
            #print(item)
        elif os.path.isdir(item):
            remote_subfolder = os.path.join(remote_path, os.path.basename(item))
            scp.put(item, recursive=True, remote_path=remote_subfolder)
            copy_files_recursive(scp, item, remote_subfolder, exclude_item)
        
        
        #print('item-> ', item)

def upload_folder(host, port, username, password, local_folder, remote_path, command, send_bot_folder:bool = True):
    #try:
    # Создаем клиент SSH
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Подключаемся к серверу
    client.connect(hostname=host, port=port, username=username, password=password)
    #stdin, stdout, stderr = client.exec_command(f"sudo -S rm -r /home/server/tg_build_bot/information_telegram_bot")
    stdin, stdout, stderr = client.exec_command(f"sudo -S ls")
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
        #scp.put(local_folder, recursive=True, remote_path=remote_path)
        copy_files_recursive(scp, '.', remote_path + '/information_telegram_bot', ['.git', '__pycache__'])
        # отправляем файлы бота
        if send_bot_folder:
            copy_files_recursive(scp, '../', remote_path+'/bots/test_bots', ['information_telegram_bot', '.git', '__pycache__'], False)


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
    print('УСТАРЕЛО')
    exit()
    saved_datetime = read_datetime_from_file('datetime.txt')
    save_datetime_to_file('datetime.txt')

    # Параметры сервера
    host = "80.78.243.187"
    port = 22  # Порт SSH
    username = "server"
    password = "serverqwe123"

    # Перезатирать данные бота
    send_bot_folder = False

    # Локальная папка, которую нужно передать
    local_folder = "../information_telegram_bot"

    # Путь на сервере, куда нужно передать папку
    remote_path = "/home/server/tg_build_bot"

    # Команда для выполнения под sudo
    command = "supervisorctl reload"

    # Вызываем функцию для загрузки папки и выполнения команды
    upload_folder(host, port, username, password, local_folder, remote_path, command, send_bot_folder=send_bot_folder)
