import curses

class ConsoleOption:
    option_list: list
    chosen_option = None

    def __str__(self):
        return self.chosen_option

    def _display_menu(self, stdscr, options):
        stdscr.clear()
        curses.curs_set(0)  # Скрыть курсор
        
        current_row = 0
        top_row = 0  # верхняя видимая строка в случае большого списка

        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Рассчитаем количество видимых строк
            visible_rows = height - 2  # вычитаем 2 для отступов сверху и снизу

            # Проверим, если текущая строка не видна, сдвинем верхнюю видимую строку
            if current_row < top_row:
                top_row = current_row
            elif current_row >= top_row + visible_rows:
                top_row = current_row - visible_rows + 1

            # Отобразим видимые строки
            for idx in range(len(options)):
                if top_row <= idx < top_row + visible_rows:
                    option = options[idx]
                    
                    # Проверка ширины и обрезка строки, если она длиннее ширины окна
                    if len(option) > width - 1:
                        option = option[:width - 1]

                    x = max(0, width // 2 - len(option) // 2)  # Проверяем, чтобы x был не меньше 0
                    y = height // 2 - len(options) // 2 + (idx - top_row)
                    
                    if 0 <= y < height:  # Проверяем, чтобы y был в пределах окна
                        if idx == current_row:
                            stdscr.attron(curses.A_REVERSE)
                            stdscr.addstr(y, x, option)
                            stdscr.attroff(curses.A_REVERSE)
                        else:
                            stdscr.addstr(y, x, option)

            key = stdscr.getch()
            
            if key == curses.KEY_DOWN:
                current_row = (current_row + 1) % len(options)
            elif key == curses.KEY_UP:
                current_row = (current_row - 1) % len(options)
            elif key == 10:  # Enter key
                return options[current_row]
            

    def _run_chosen_menu(self, stdscr):
        self.chosen_option = self._display_menu(stdscr, self.option_list)
        stdscr.refresh()

    def chosen_menu(self, option_list) -> str:
        self.option_list = option_list
        curses.wrapper(self._run_chosen_menu)
        return self.chosen_option
    

def select_option_menu(option_list):
    return ConsoleOption().chosen_menu(option_list)

    
if __name__ == "__main__":
    opt_men = ConsoleOption()
    print(ConsoleOption().chosen_menu(['1', '2', '3']))
    print(ConsoleOption().chosen_menu(['2', '2', '3']))
    print(ConsoleOption().chosen_menu(['3', '2', '3']))