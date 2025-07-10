from send_site_to_server_3 import run_update
from supervisor_server import run_connect
from console_mgt import select_option_menu


if __name__ == "__main__":
    options_names = [
        'залить правки',
        'коммманды',
        'ВЫХОД'
    ]


    server_folder_name = select_option_menu(options_names) #chosen_option
    if server_folder_name == 'ВЫХОД':
        exit()
        
    elif server_folder_name == 'залить правки':
        run_update()
    elif server_folder_name == 'коммманды':
        run_connect()