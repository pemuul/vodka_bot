""" Наш файл требует обработки и зугрузки, этим мы и должны заняться """

import json
import difflib
import os
import shutil

from exception_error_json_tree import ValidJSONData, IdAlreadyExists, IdIsNotReal
from keys import SPLITTER_STR


def create_folder(path):
    # Проверяем, существует ли папка по указанному пути
    if not os.path.exists(path):
        # Если не существует, создаем папку
        os.makedirs(path)


def copy_or_rename_file(source_folder, destination_folder, filename, new_filename):   
    current_directory = os.path.dirname(os.path.abspath(__file__))
    current_directory = os.path.join(current_directory, destination_folder)
    
    source_path = os.path.join(source_folder, filename)
    destination_path = os.path.join(current_directory, new_filename)

    # Проверяем, существует ли файл в исходном каталоге
    if not os.path.exists(source_path):
        # Если файл не существует, копируем его
        shutil.copy(destination_path, source_path)


class TreeObject:
    path = None
    next_layers = {}
    previous_layer = None
    text = None
    media = None
    item_id = None
    key = None
    redirect = None

    def __init__(self, key, obj_in_dict) -> None:
        self.key = key

        self.load_data_from_dict(obj_in_dict)
    
    def load_data_from_dict(self, obj_in_dict):
        self.text = obj_in_dict.get('text')
        self.media = obj_in_dict.get('media')
        self.item_id = obj_in_dict.get('id')

        #self.next_layers = list(obj_in_dict.keys())

    def __str__(self) -> str:
        return str(vars(self))
    
    def get_dict_element(self):
        dict_element = {}
        if self.redirect:
            dict_element['redirect'] = self.redirect
            return dict_element

        if self.item_id:
            dict_element['id'] = self.item_id

        if self.text:
            dict_element['text'] = self.text

        if self.media:
            dict_element['media'] = self.media

        if self.next_layers != {}:
            next_layers = self.next_layers
            next_buttons = list(next_layers.keys())

            for button in next_buttons:
                next_element = self.next_layers[button]
                dict_element[next_element.key] = next_element.get_dict_element()

        return dict_element

    
    def save_to_file(self, file_name='test.json'):
        dict_to_file = self.get_dict_element()

        with open(file_name, 'w', encoding='utf-8') as new_file:
            json.dump(dict_to_file, new_file, ensure_ascii=False, indent=2)



class Tree_data():
    id_dict = {} # список всех id в дереве даннвх
    path_to_id = {} # все нахождения всех пунктов в ветках, id как элемент, чтобы было понятно какой id у папки
    id_to_path = [] # все пути расположенные по порядку, чтобы проще было найти их по id
    id_path_to_id = 0 # текущий id пути, для правильного расположения путей

    id_dict_preload = {} # нужен временный id, чтобы проверка не сломала текущие настройки

    tree_obj = None # основной объект, который мы собираем

    main_file_name = None # основной файл, в котором схема данных

    # теги, которые содержат функциональный контент, можно изменить
    special_words = ['text', 'media', 'id', 'redirect']

    test_file_name = 'test.json'

    def __init__(self, main_file_name):
        self.main_file_name = main_file_name

        self.check_json_file_valid()
        self.create_obj_data_from_json()
        #raise ValidJSONData('123')


    # << ======================= проверка, что после загрузки не теряем данные =======================
    def _comparison_load_json_file(self, file_name, get_error=False) -> None:
        # загружаем, сохраняем и опять загружаем, а после сравниваем
        # даст ошибки, в основном неправильное оформление файла
        with open(file_name, 'r') as file:
            dict_file = json.load(file)

        with open(self.test_file_name, 'w', encoding='utf-8') as new_file:
            json.dump(dict_file, new_file, ensure_ascii=False, indent=2)

        with open(file_name, 'r', encoding='utf-8') as old_file:
            file_text_preload = old_file.read()

        with open(self.test_file_name, 'r', encoding='utf-8') as old_file:
            file_text_load = old_file.read()

        os.remove(self.test_file_name)
        
        # Сравнение строк
        differ = difflib.Differ()
        diff = list(differ.compare(file_text_preload.splitlines(), file_text_load.splitlines()))

        return_text = None

        # Если есть различия, выводим их
        if any(line.startswith(('+', '-')) for line in diff):
            return_text = f"При загрузке файла появились расхождения:\n"
            for line in diff:
                if line.startswith(('+', '-')):
                    return_text += line + '\n'
            
            return_text += '\n'
            return_text += 'Скроее всего, у вас на одном уровне два одинаковых заголовка!'
            return_text += '\nИли неправильное оформление файла, например, пробел перед :'
        
        if get_error:
            return return_text

        if return_text:
            raise ValidJSONData(return_text)
    # >> ======================= проверка, что после загрузки не теряем данные =======================


    def get_obj_from_path(self, path) -> TreeObject:
        # у нас в дереве все зацеплено друг за друга, поэтому мы для получения нужного объекта проваливаемя по порядку по веткам
        path_list = path.split(SPLITTER_STR)
        path_list = [value for value in path_list if value]

        tree_obj = self.tree_obj
        for key_name in path_list:
            tree_obj = tree_obj.next_layers[key_name]

        return tree_obj


    # << ================== Подргужаем из файлла данные в объект ==================
    def _remove_special_word(self, keys_next_layer):
        # удаляем специальные теги, которые не нужны в обработке 
        for special_word in self.special_words:
            if special_word in keys_next_layer:
                keys_next_layer.remove(special_word)


    def _add_path(self, path):
        self.path_to_id[path] = self.id_path_to_id
        self.id_path_to_id += 1


    ''' мы должны построить дерево из всех данных '''
    def _create_tree_obj(self, tree_obj_item, key_name='menu', old_tree_obj_item=None):
        keys_next_layer = list(tree_obj_item.keys())

        # удаляем специальные теги, которые не нужны в обработке 
        self._remove_special_word(keys_next_layer)

        if old_tree_obj_item:
            path = old_tree_obj_item.path
            if path[-len(SPLITTER_STR):] != SPLITTER_STR:
                path += SPLITTER_STR
            path += key_name
        else:
            path = SPLITTER_STR

        id_item = tree_obj_item.get('id')
        if id_item:
            if self.id_dict.get(id_item):
                #print(f'ОШИБКА уже есть такой ключ: {id_item}')
                raise IdAlreadyExists(id_item)
            
            self.id_dict[id_item] = path

        tree_obj = TreeObject(key_name, tree_obj_item)

        tree_obj.path = path
        self._add_path(path)

        next_layers = {}
        for key_next_layer in keys_next_layer:
            next_layers[key_next_layer] = self._create_tree_obj(tree_obj_item[key_next_layer], key_next_layer, tree_obj)
            
        tree_obj.previous_layer = old_tree_obj_item
        tree_obj.next_layers = next_layers

        return tree_obj
    

    # после загрузки всего файла, мы получили объекты и подгрузилии им их id
    # теперь мы созадём ссылки на редеректных ветках
    def _set_redirect_to_tree(self, tree_obj_json, path=SPLITTER_STR):
        keys_next_layer = list(tree_obj_json.keys())

        self._remove_special_word(keys_next_layer)

        redirect = tree_obj_json.get('redirect')
        if redirect:
            redirect_path = self.id_dict.get(redirect)
            if not redirect_path:
                raise IdIsNotReal(redirect)
            obj_find = self.get_obj_from_path(redirect_path)
            path_list = path.split(SPLITTER_STR)
            obj_replace = self.get_obj_from_path(path)
            obj_replace.next_layers[path_list[-1]] = obj_find
            obj_replace.next_layers = obj_find.next_layers
            obj_replace.text = obj_find.text
            obj_replace.media = obj_find.media 
            obj_replace.redirect = redirect

        next_layers = {}
        for key_next_layer in keys_next_layer:
            new_path = path
            if new_path[-len(SPLITTER_STR):] != SPLITTER_STR:
                new_path += SPLITTER_STR
            new_path += key_next_layer
            next_layers[key_next_layer] = self._set_redirect_to_tree(tree_obj_json[key_next_layer], new_path)
        
        return next_layers
    

    def get_path_to_id(self, path):
        return self.path_to_id.get(path)
    

    def get_id_to_path(self, id_path): 
        return self.id_to_path[id_path]
                

    # подгружаем полностью файл из данных
    def create_obj_data_from_json(self, file_name=None) -> TreeObject:
        if file_name is None:
            file_name = self.main_file_name
        else:
            self.main_file_name = file_name

        # перед заливкой обновляем все данные 
        self.id_to_path = []
        self.path_to_id = {}
        self.id_path_to_id = 0
        self.id_dict = {}

        with open(file_name, 'r') as file:
            tree_json_data = json.load(file)

        tree_obj_data = self._create_tree_obj(tree_json_data)
        self.tree_obj = tree_obj_data
        self._set_redirect_to_tree(tree_json_data)

        for path_id in list(self.path_to_id.keys()):
            self.id_to_path.append(path_id)
   

        return self.tree_obj
    # >> ================== Подргужаем из файлла данные в объект ==================


    # << ================== Проверка, что данные в файле корректны ==================
    def _checking_json_data_is_normal(self, tree_json_data, key_name='menu', path=SPLITTER_STR):
        keys_layer = list(tree_json_data.keys())
        keys_next_layer = list(keys_layer)
        error_list = []

        self._remove_special_word(keys_next_layer)

        if "redirect" in keys_layer:
            if len(keys_layer) > 1:
                error_list.append(f'В элементе с параметром redirect может быть только параметр redirect "{key_name}"')

        if "id" in keys_layer:
            id_name = tree_json_data.get('id')
            if self.id_dict_preload.get(id_name):
                error_list.append(f'Дважды указан id {id_name}')

            self.id_dict_preload[tree_json_data.get('id')] = path

        for key_next_layer in keys_next_layer:
            new_path = path
            if new_path[-len(SPLITTER_STR):] != SPLITTER_STR:
                new_path += SPLITTER_STR
            new_path += key_next_layer
            error_list += self._checking_json_data_is_normal(tree_json_data[key_next_layer], key_next_layer, new_path)

        return error_list


    # проверяем, что все указанныередиректы ссылаются на существующие id
    def _id_is_real(self, tree_json_data):
        keys_layer = list(tree_json_data.keys())
        keys_next_layer = list(keys_layer)
        error_list = []

        self._remove_special_word(keys_next_layer)

        if "redirect" in keys_layer:
            redirect = tree_json_data.get('redirect')
            if not self.id_dict_preload.get(redirect):
                error_list.append(f'id {redirect} не найден в файле')

        for key_next_layer in keys_next_layer:
            error_list += self._id_is_real(tree_json_data[key_next_layer])

        return error_list


    # проверяем, что файл подходит всем нашим стандартам
    def check_json_file_valid(self, file_name=None, get_error=False):
        if not file_name:
            file_name = self.main_file_name
        
        error_list = []
        self.id_dict_preload = {}
        
        try:
            error_load_file = self._comparison_load_json_file(file_name, get_error=True)
            if error_load_file:
                error_list.append(error_load_file)

            with open(file_name, 'r') as file:
                dict_file = json.load(file)

            error_list += self._checking_json_data_is_normal(dict_file)
            error_list += self._id_is_real(dict_file)

        except Exception as e:
            error_text = f'Произошла непредвиденная ошибка: {e}'
            print(error_text)
            error_list.append(error_text)

        if not get_error and len(error_list) > 0:
            raise ValidJSONData(error_list=error_list) 

        return error_list
    
# >> ================== Проверка, что данные в файле корректны ==================


if __name__ == "__main__":
    # Мы первоначально строим дерево из всех данных
    tree_data = Tree_data('tree_data.json')
    print(tree_data.tree_obj)

    print(tree_data.check_json_file_valid('tree_data_copy.json', get_error=True))
    tree_data.create_obj_data_from_json('tree_data_copy.json')

    #error_list = tree_data.check_json_file_valid(main_file)

    #if not error_list:
        # Открываем файл на чтение
        #with open(main_file, 'r') as file:
        #    tree_json_data = json.load(file)
    #    print(tree_data.create_obj_data_from_json(main_file))
    #else:
    #    print(error_list)

    #print(checking_json_data_is_normal(tree_json_data))
    #print(tree_json_data)

    #print(comparison_load_json_file(main_file))