

class ValidJSONData(Exception):
    def __init__(self, message=None, error_list=None):
        self.message = message
        self.error_list = error_list
        super().__init__(self.message)
    
    def __str__(self):
        if self.error_list:
            error_text = 'При загрузки данных произошли такие ошибки:\n'
            for error in self.error_list:
                error_text += str(error) + '\n'
        else:
            error_text = f"При загрузки данных произошла ошибка: {self.message}"

        return error_text
    
    
class IdAlreadyExists(Exception):
    def __init__(self, id_tree):
        self.id_tree = id_tree
        self.message = f'Вы дважды указали id: {id_tree} в файле конфигурации!'
        super().__init__(self.message)
    
    def __str__(self):
        return self.message
    

class IdIsNotReal(Exception):
    def __init__(self, id_tree):
        self.id_tree = id_tree
        self.message = f'Вы указали id: {id_tree}, которого не существует (вы его не прописали)!'
        super().__init__(self.message)
    
    def __str__(self):
        return self.message