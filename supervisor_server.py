import paramiko
import os
import time
import gc
import sys
from console_mgt import select_option_menu


host = "80.78.243.187"
port = 22  # Порт SSH
username = "server"
password = "serverqwe123"


client:paramiko.SSHClient = None

def connect():
    global client

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Подключаемся к серверу
    client.connect(hostname=host, port=port, username=username, password=password)


def get_supervisor_process() -> list:
    stdin, stdout, stderr = client.exec_command('sudo -S supervisorctl status')
    stdin.write(password + '\n')
    stdin.flush()

    # Получаем результат выполнения команды
    output = stdout.read().decode().strip()

    processes = []
    for line in output.splitlines():
        parts = line.split()
        process = {
            "name": parts[0],
            "state": parts[1],
            "pid": int(parts[3].strip(',')) if parts[1] == 'RUNNING' else None,
            "uptime": ' '.join(parts[4:]) if parts[1] == 'RUNNING' else None
        }
        processes.append(process)

    return processes


def select_supervisor_process(not_select_item=[], plus_option=[]) -> str:
    processes = get_supervisor_process()
    return select_option_menu([process['name'] for process in processes if process['name'] not in not_select_item] + plus_option)


def command_process(command, process_name):
    stdin, stdout, stderr = client.exec_command(f'sudo -S supervisorctl {command} {process_name}')
    stdin.write(password + '\n')
    stdin.flush()


def draw_dot(show=True):
    if show:
        sys.stdout.write('\r.')  # Рисуем точку
    else:
        sys.stdout.write('\r ')  # Стираем точку (заменяем пробелом)
    sys.stdout.flush()  # Принудительно выводим на экран


def run_select():
    command_start = [
        'запустить бота под собой',
        'комманды над ботом',
        'перезапустить всё',
        'остановить все python процессы',
        'статус',
        'УДАЛИТЬ БОТА',
        'ВЫЙТИ'
    ]

    option_menu = select_option_menu(command_start)

    if option_menu == 'запустить бота под собой':
        bot_name = select_supervisor_process(plus_option=['ВЫХОД'])
        if bot_name == 'ВЫХОД':
            exit()  

        conf_dir = '/etc/supervisor/conf.d'
        stdin, stdout, stderr = client.exec_command(f'ls {conf_dir}')
        conf_files = stdout.read().decode().splitlines()

        # Ищем файл с именем процесса
        process_conf_file = None
        for conf_file in conf_files:
            if bot_name in conf_file:
                process_conf_file = os.path.join(conf_dir, conf_file)
                break

        if not process_conf_file:
            #client.close()
            raise FileNotFoundError(f"Файл конфигурации для процесса {bot_name} не найден.")

        # Читаем файл конфигурации
        stdin, stdout, stderr = client.exec_command(f'cat {process_conf_file}')
        conf_content = stdout.read().decode().splitlines()

        # Ищем строку с directory=
        directory = None
        for line in conf_content:
            if line.startswith('directory='):
                directory = line.split('=')[1].strip()
            elif line.startswith('command='):
                venv_path = line.split('=')[1].strip()

        #client.close()

        if not directory:
            raise ValueError(f"Строка с 'directory=' не найдена в конфигурации процесса {bot_name}.")
        
        print(directory)

        #client.exec_command(f'cd {directory}')
        # Запуск скрипта через виртуальное окружение
        run_file = venv_path.split(' ')[1]
        if run_file == '-w':
            run_file = 'run_site.py'
            venv_path = venv_path.replace('gunicorn', 'python')
        command = f'cd {directory} && {venv_path.split(" ")[0]} {run_file} & echo $! > {directory}/pid.txt'
        print(command)
        try:   
            # Постоянный вывод данных
            command_process('stop', bot_name)
            time.sleep(1)

            command = f'/home/server/run_bot_ssh.sh {directory} {run_file} {venv_path.split(" ")[0]}'
            stdin, stdout, stderr = client.exec_command(command, get_pty=True)

            command_cat = f'cat {directory}/pid.txt'
            print(command_cat)
            stdin_pid, stdout_pid, stderr_pid = client.exec_command(command_cat)
            pid = stdout_pid.read().decode().strip()
            print(pid)

            output = None
            error = None
            #while not stdout.channel.exit_status_ready() or (pid == None):
            dot = True
            while True:
                # Проверка на наличие доступного вывода
                if stdout.channel.recv_ready():
                    output = stdout.channel.recv(1024).decode('utf-8', errors='ignore')
                    print(output, end='')

                # Проверка на наличие доступных ошибок
                if stderr.channel.recv_ready():
                    error = stderr.channel.recv(1024).decode('utf-8', errors='ignore')
                    print(error, end='')

                # Проверка, завершился ли процесс
                if stdout.channel.exit_status_ready():
                    break

                draw_dot(dot)
                dot = dot is False

                time.sleep(1)
            
        except Exception as e:
            print('ERROR -> ', e)
        finally:
            try:
                # Закрытие соединения
                command_process('start', bot_name)
                client.exec_command(f'kill {pid}')
                client.exec_command(f'kill {int(pid) + 1}')
                #client.close()
                #gc.collect()
                print('Процесс окончен')
            except Exception as e:
                print('ERROR -> ', e)
                print('ИДЁТ ПЕРЕЗАПУСК НА СЕРВЕРЕ')
                client.close()
                gc.collect()
                connect()
                command_process('start', bot_name)
                client.exec_command(f'kill {pid}')
                client.exec_command(f'kill {int(pid) + 1}')
                client.close()
                gc.collect()
                print('Процесс окончен')
            

        # Получение оставшегося вывода после завершения
        #output = stdout.read().decode('utf-8')
        #error = stderr.read().decode('utf-8')

        #print(output)
        #print(error)


    elif option_menu == 'комманды над ботом':
        bot_name = select_supervisor_process(plus_option=['ВЫХОД'])
        if bot_name == 'ВЫХОД':
            exit()

        command_bots = [
            'запустить',
            'остановить',
            'перезапустить',
            'ВЫЙТИ'
        ]
        option_menu_command = select_option_menu(command_bots)

        if option_menu_command == 'запустить':
            command_process('start', bot_name)
        elif option_menu_command == 'остановить':
            command_process('stop', bot_name)
        elif option_menu_command == 'перезапустить':
            command_process('restart', bot_name)
        else:
            print('команда не найдена')
        print(f'Для бота {bot_name} была выполнена команда "{option_menu_command}"')
    elif option_menu == 'перезапустить всё':
        stdin, stdout, stderr = client.exec_command(f'sudo -S supervisorctl reload')
        stdin.write(password + '\n')
        stdin.flush()    

    elif option_menu == 'остановить все python процессы':
        client.exec_command(f'pkill python')
        client.exec_command(f'pkill python3') 
        client.exec_command(f'pkill gunicorn') 

    elif option_menu == 'статус':
        bots = get_supervisor_process()
        print(bots)

        name_width = max(len(bot['name']) for bot in bots) + 2
        state_width = max(len(bot['state']) for bot in bots) + 2
        pid_width = 5
        uptime_width = max(len(str(bot['uptime'])) for bot in bots) + 2

        # Выводим заголовки
        print(f"{'Name':<{name_width}}{'State':<{state_width}}{'PID':<{pid_width}}{'Uptime':<{uptime_width}}")
        print('-' * (name_width + state_width + pid_width + uptime_width))

        # Выводим строки с данными
        for bot in bots:
            print(f"{bot['name']:<{name_width}}{bot['state']:<{state_width}}{str(bot['pid']):<{pid_width}}{str(bot['uptime']):<{uptime_width}}")
    elif option_menu == 'УДАЛИТЬ БОТА':
        bot_name = select_supervisor_process(plus_option=['ВЫХОД'])
        if bot_name == 'ВЫХОД':
            exit()

        select_option = select_option_menu(['Точно хотите удалить?', 'ДА', 'НЕТ'])
        if select_option != 'ДА':
            exit()
        
        stdin, stdout, stderr = client.exec_command(f'sudo -S /home/server/delete_bot.sh {bot_name}', get_pty=True)
        stdin.write(password + '\n')
        stdin.flush()

        # Получение результата выполнения команды
        stdout_lines = stdout.readlines()
        stderr_lines = stderr.readlines()

        # Вывод результатов
        print("Стандартный вывод:")
        for line in stdout_lines:
            print(line.strip())

        print("Стандартный поток ошибок:")
        for line in stderr_lines:
            print(line.strip())
        
        print(f'Бот {bot_name} удалён!')


def run_connect():
    connect()
    try:    
        run_select()
    except Exception as e:
        print('ERROR -> ', e) 
    finally:
        try:
            client.close()
            #gc.collect()
            print('Подключение закрыто')
        except:
            pass


if __name__ == "__main__":
    run_connect()