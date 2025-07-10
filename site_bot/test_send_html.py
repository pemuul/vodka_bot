import requests
import os

url = 'https://designer-tg-bot.ru/upload'
api_key = 'sfdijo48j-2f4-df'

# Путь к папке, содержащей файлы
folder_path = '.'

def upload_files_from_folder(folder_path):
    headers = {'Authorization': f'Bearer {api_key}'}
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.endswith('.html') or filename.endswith('.js') or filename.endswith('.css')\
                or filename.endswith('.png') or filename.endswith('.svg'):
                file_path = os.path.join(root, filename)
                if os.path.isfile(file_path):
                    with open(file_path, 'rb') as f:
                        files = {'file': f, "file_path": str(file_path)}
                        data = {'file_path': file_path} 
                        print(files, data)
                        response = requests.post(url, files=files, data=data, headers=headers)

                        try:
                            print(response, response.json())  
                        except: 
                            print(response)

upload_files_from_folder(folder_path)
