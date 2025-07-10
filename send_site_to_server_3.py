import paramiko
import os
from scp import SCPClient
import datetime
import json
import curses
from console_mgt import select_option_menu

client = None
server_folder_name = None
old_folder = None
saved_datetime = None


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
restert_all = False # нужно ли перезапустить supervisorctl
command = "supervisorctl reload"
old_folder = 20 # сколько хранить папок в архиве при заливке

file_path = 'datetime.json'


def save_datetime_to_file(file_path, folder_key):
    current_datetime = datetime.datetime.now()
    
    # Проверяем, существует ли файл
    if os.path.exists(file_path):
        # Если файл существует, читаем его содержимое
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
        except json.JSONDecodeError:
            # Если файл пустой или содержит некорректные данные, создаём новый словарь
            data = {}
    else:
        # Если файла нет, создаём новый словарь
        data = {}

    # Обновляем или добавляем новое значение по ключу
    data[folder_key] = current_datetime.isoformat()

    # Записываем обновлённые данные обратно в файл
    with open(file_path, 'w') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

def read_datetime_from_file(file_path, folder_key):
    try:
        # Читаем из файла
        with open(file_path, 'r') as file:
            data = json.load(file)
            datetime_str = data.get(folder_key)
            if datetime_str:
                # Преобразуем строку ISO в объект datetime
                return datetime.datetime.fromisoformat(datetime_str)
            else:
                return datetime.datetime(1900, 1, 1, 0, 0, 0)
    except FileNotFoundError:
        # Возвращаем время 1900 года, если файл не найден
        return datetime.datetime(1900, 1, 1, 0, 0, 0)
    except ValueError:
        # Обработка случая, если формат даты в файле неверен
        raise ValueError(f"Дата в файле {file_path} имеет неверный формат")

# Функция для получения списка файлов и папок в локальной папке
def get_files_and_folders(path, exclude_item):
    items = []
    for item in os.listdir(path):
        if not item in exclude_item:
            #if datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(path, item))) > saved_datetime:
            items.append(os.path.join(path, item))
        #print('- path -> ', path, item)
    return items

# Функция для создания каталога на сервере, если его нет
def create_remote_directory(client, remote_path):
    stdin, stdout, stderr = client.exec_command(f'mkdir -p {remote_path}')
    stdout.channel.recv_exit_status()  # Ждем завершения команды

# Функция для рекурсивной копии файлов и папок на удаленный сервер
def copy_files_recursive(scp, local_path, remote_path, exclude_item, is_fromtimestamp=True):
    global client
    
    send_file_list = []

    # Создаем удаленный каталог, если его нет
    #print('remote_path -> ', remote_path)
    create_remote_directory(client, remote_path)

    for item in get_files_and_folders(local_path, exclude_item):
        if os.path.isfile(item):
            # Проверяем, что время изменения файла меньше сегодняшнего утра
            file_mtime = os.path.getmtime(item)
            send_file = True
            if is_fromtimestamp:
                send_file = datetime.datetime.fromtimestamp(file_mtime) > saved_datetime

            #print('--> ', item)
            if send_file:
                send_file_list.append([item, remote_path])

            #print(datetime.datetime.fromtimestamp(file_mtime), saved_datetime)
            #print(item)
        elif os.path.isdir(item):
            remote_subfolder = os.path.join(remote_path, os.path.basename(item))
            #scp.put(item, recursive=True, remote_path=remote_subfolder)
            copy_files_recursive(scp, item, remote_subfolder, exclude_item)
        #print('-> ', item)

    for send_file in send_file_list:
        print(send_file[0])
        scp.put(send_file[0], send_file[1])

def upload_folder(host, port, username, password, local_folder, remote_path, command, send_bot_folder:bool = True):
    #try:
    global client
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
    print(output, errors)
    # Закрываем предыдущие stdin, stdout, stderr

    client.exec_command(f'cp -r {remote_path + "/" + server_folder_name} {remote_path}/old/{server_folder_name}_$(date +"%Y-%m-%d_%H-%M-%S")')
    client.exec_command(f"find /home/server/tg_build_bot/old -maxdepth 1 -type d -exec stat --format '%Y %n' {'{}'} \; | sort -nr | tail -n +{old_folder + 2} | cut -d' ' -f2 | xargs rm -rf")

    # Создаем экземпляр SCPClient
    with SCPClient(client.get_transport()) as scp:
        # Загружаем локальную папку на сервер, заменяя существующую
        #scp.put(local_folder, recursive=True, remote_path=remote_path)
        copy_files_recursive(scp, '.', remote_path + '/' + server_folder_name, ['.git', '__pycache__'])
        # отправляем файлы бота
        if send_bot_folder:
            copy_files_recursive(scp, '../', remote_path+'/bots/test_bots', ['information_telegram_bot', '.git', '__pycache__'], False)


    print(f"Папка {local_folder} успешно передана на сервер по пути {remote_path}")

    # Выполняем команду с sudo
    if restert_all:
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

def run_update():
    global saved_datetime
    global server_folder_name
    #server_folder_name = 'information_telegram_bot'
    #server_folder_name = 'v_2'
    options_names = ['information_telegram_bot', '----', 'v_2'] # варианты версий, куда заливать файлы


    #curses.wrapper(chosen_menu)
    server_folder_name = select_option_menu(options_names) #chosen_option
    if server_folder_name == '----':
        exit()

    saved_datetime = read_datetime_from_file(file_path, server_folder_name)

    # Вызываем функцию для загрузки папки и выполнения команды
    upload_folder(host, port, username, password, local_folder, remote_path, command, send_bot_folder=send_bot_folder)


    save_datetime_to_file(file_path, server_folder_name)



if __name__ == "__main__":
    run_update()