
// ------- Нижние кнопки -------
const bottom_block_btn = document.getElementById('bottom-block');
const orders_bottom_btn = document.getElementById('orders-bottom-btn');
const items_bottom_btn = document.getElementById('items-bottom-btn');
const settings_bottom_btn = document.getElementById('settings-bottom-btn');

// ------- Заказ -------
const orders_div = document.getElementById('orders');
const order_div = document.getElementById('order');
const order_setting_div = document.getElementById('order-setting');
const cart_order_div = document.getElementById('cart-order');
const order_add_item = document.getElementById('order-add-item');
const order_edit_line = document.getElementById('order-edit-line');

// ------- Товары -------
const items_div = document.getElementById('items');
const item_div = document.getElementById('item');
const item_setting_div = document.getElementById('item-setting');

// ------- Настройка -------
const settings_div = document.getElementById('settings');
const settings_admins_div = document.getElementById('settings-admins');
const settings_awaiting_payment_div = document.getElementById('settings-awaiting-payment');
const settings_API_div = document.getElementById('settings-API');
const settings_open_admins_btn = document.getElementById('settings-open-admins-btn');

// ------- Получаем для запросов -------
var currentURL = window.location.href;
var urlWithoutParams = currentURL.split('?')[0];
//const urlTgParams = urlWithoutParams.split('#')[0];
const urlTgParams = 'https://designer-tg-bot.ru/gAAAAABmECxzjzjd693OWoAgJrRP6u-SwQ9-FOnyGDRHuBrHnIr4lNbQ4kjeEP4cN33Z9BDdQX282j4dQiPu7roVUM9oPZSXoI_SuMJ8zXjiGO_a_KaxXyzGfOS516uEkUQCg8AEgPgn'
const DomainUrl = 'https://designer-tg-bot.ru/';


 //------- Обрабатываем нажатие кнопок -------
orders_bottom_btn.addEventListener('click', () => {
    setMenuDiv('orders');
});

items_bottom_btn.addEventListener('click', () => {
    setMenuDiv('items');
});

settings_bottom_btn.addEventListener('click', () => {
    setMenuDiv('settings');
});


function setBottom() {
    bottom_block_btn.style.display = 'flex'; 
}

function closeBottom() {
    bottom_block_btn.style.display = 'none'; 
}

function setMenuDiv(divIdToShow) {
    setBottom();
    console.log('setMenuDiv --> вызвался')
    console.log(divIdToShow)
    var menuDivs = document.querySelectorAll('.menu-div'); // Получаем все div'ы с классом "menu-div"
    for (var i = 0; i < menuDivs.length; i++) {
        if (menuDivs[i].id === divIdToShow) {
            menuDivs[i].style.display = 'block'; // Показываем div, если его id совпадает с переданным аргументом
            if (menuDivs[i].classList.contains('all-size')) {
                closeBottom();
            }
        } else {
            menuDivs[i].style.display = 'none'; // Скрываем остальные div'ы
        }
    }
}


var tg = window.Telegram.WebApp;
tg.expand();

const tg_id = tg.initDataUnsafe.user && tg.initDataUnsafe.user.id ? tg.initDataUnsafe.user.id : 1001;
console.log(tg_id);

// ------- Настройка -------
var admins_list;
var awaiting_fields_list;

document.getElementById('settings-open-admins-btn').addEventListener('click', async function () {
    await openSettingsAdmins();
});


async function getAdmins() {
    try {
        const response = await fetch(urlTgParams + '/get_admins', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        return data.admins; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}


async function updateAdminRule(rule, should_add_it) {
    //alert(`Не реализованно updateAdminRule(${rule}, ${should_add_it})`); 
    try {
        const response = await fetch(urlTgParams + '/update_admin_rule', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, add_rule: should_add_it, rule: rule })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        return data.admins; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function openSettingsAdmins() {
    // открываем меню настроек админов

    admins_list = await getAdmins();
    console.log(admins_list);

    const cart_setting_admins = document.getElementById('cart-setting-admins');
    cart_setting_admins.innerHTML = '';

    admins_list.forEach(admin => {
        const adminsInfo = document.createElement('div');
        adminsInfo.innerHTML = `

                    <div class="manager" style="margin-bottom: 20px;">
                        <div class="manager-info" style="display: flex;">
                            <div class="avatarMenager" id="avatarMenager"></div>
                            <div class="details">
                                <p>${admin.user.name}</p>
                                <p>${admin.rule}</p>
                                <p>Получать сообщения: <input type="checkbox" id="admin-is-manager-${admin.user_tg_id}" ${admin.rule.includes('GET_INFO_MESSAGE') ? 'checked' : ''}></p>
                                <p>Контакт для обратной связи: <input type="checkbox" id="admin-is-contact-manager-${admin.user_tg_id}" ${admin.rule.includes('CONTACT_MANAGER') ? 'checked' : ''}></p>
                            </div>
                        </div>
                    </div>
                `;
        cart_setting_admins.appendChild(adminsInfo);

        document.getElementById(`admin-is-manager-${admin.user_tg_id}`).addEventListener('change', async function () {
            await updateAdminRule('GET_INFO_MESSAGE', this.checked);
        });

        document.getElementById(`admin-is-contact-manager-${admin.user_tg_id}`).addEventListener('change', async function () {
            await updateAdminRule('CONTACT_MANAGER', this.checked);
        });
    })

    setMenuDiv('settings-admins');
}

async function getAwaitingFields(type, field) {
    try {
        const response = await fetch(urlTgParams + '/get_awaiting_fields', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })
        });
        const data = await response.json();
        return data.awaiting_fields; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function updateAwaitingFields(type, field) {
    try {
        const response = await fetch(urlTgParams + '/update_awaiting_fields', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, type: type, field: field })
        });
        const data = await response.json();
        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function getAwaitingField(field_no) {
    return awaiting_fields_list[field_no]
}

async function openSettingsFields() {
    awaiting_fields_list = await getAwaitingFields();

    const cart_setting_awaiting_payment = document.getElementById('cart-setting-awaiting-payment');
    //cart_setting_awaiting_payment.innerHTML = '';

    cart_setting_awaiting_payment.innerHTML = `
        <button class="btn" style="border-radius: 5px; padding: 2%;" id="add-awaiting-field">
            <img style="width: 20px;" src="icon/Plus.png">
            Добавить
        </button>
    `;

    var last_index = -1;
    awaiting_fields_list.map((awaiting_field, index) => {
        const awaiting_fieldInfo = document.createElement('div');
        awaiting_fieldInfo.innerHTML = `
                <div style="margin-bottom: 20px;">
                    <div class="nameInput">
                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                        <label for="min-order">Название</label>
                    </div>
                    <div class="textareaInput">
                        <input type="number" id="min-order" value="${awaiting_field.name}"
                            style="width: 90%; padding: 3px 5px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>

                    <div class="nameInput">
                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                        <label for="min-order">Подсказка</label>
                    </div>
                    <div class="textareaInput">
                        <input type="number" id="min-order" value="${awaiting_field.description}"
                            style="width: 40%; padding: 3px 5px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>

                    <div class="nameInput">
                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                        <label for="min-order">Тип</label>
                    </div>
                    <div class="textareaInput">
                        <input type="number" id="min-order" value="${awaiting_field.type}"
                            style="width: 40%; padding: 3px 5px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>

                    <button class="btn" style="border-radius: 5px;" id="edit-awaiting-field-${index}">
                        <img style="width: 20px;" src="icon/edit.png">
                        Редактировать
                    </button>

                </div>
                `;
        cart_setting_awaiting_payment.appendChild(awaiting_fieldInfo);

        document.getElementById(`edit-awaiting-field-${index}`).addEventListener('click', async function () {
            await openSettingField(index);
            setMenuDiv('setting-awaiting-field');
        });

        last_index = index;
    })

    document.getElementById(`add-awaiting-field`).addEventListener('click', async function () {
        awaiting_fields_list.push({
            "id": "",
            "name": "",
            "description": "",
            "type": "",
            "placeholder": "",
            "other": ""
        })

        await openSettingField(last_index + 1);
        setMenuDiv('setting-awaiting-field');
    });

    setMenuDiv('settings-awaiting-payment');
}

async function openSettingField(field_no) {
    // открываем настройку полей для ввода данных
    const awaiting_field = await getAwaitingField(field_no);

    const cart_setting_awaiting_payment = document.getElementById('cart-setting-awaiting-field');
    cart_setting_awaiting_payment.innerHTML = '';
    console.log('awaiting_field', awaiting_field);

    //awaiting_fields_list.forEach(awaiting_field => {
    const awaiting_fieldInfo = document.createElement('div');
    awaiting_fieldInfo.innerHTML = `
                <h2>Параметры поля</h2>
                <form id="form-setting-awaiting-field" enctype="multipart/form-data">
                    <input type="hidden" name="product_id" placeholder="ID поля, будет автоматически заполнено" value="${awaiting_field.id}" disabled>
                    <br>
                    <h3>Название поля:</h3>
                    <input type="text" name="product_name" placeholder="Введите названте поля" value="${awaiting_field.name}" required>
                    <br>
                    <h3>Описание поля:</h3>
                    <input type="text" name="product_description" placeholder="Введите описание поля" value="${awaiting_field.description}" required>
                    <br>
                    <h3>Тип:</h3>
                    <select id="product_type" name="product_type">
                        <option value="text" selected>Текст</option>
                        <option value="password">Пароль</option>
                        <option value="checkbox">Флажок</option>
                        <option value="number">Число</option>
                        <option value="email">Email</option>
                        <option value="url">URL</option>
                        <option value="date">Дата</option>
                    </select>
                    <br>
                    <h3>Подсказка:</h3>
                    <input type="text" name="product_placeholder" placeholder="Введите подсказку поля" value="${awaiting_field.placeholder}" required>
                    <br>
                    <input type="hidden" name="product_other" placeholder="Введите что-то ещё" value="${awaiting_field.other}" required>
                    <br>
                    <button type="button" id="save-awaiting-fields-line" class="btn">СОХРАНИТЬ</button>
                </form>
                <button type="button" id="delete-awaiting-field" class="btn">УДАЛИТЬ</button>
            `;
    cart_setting_awaiting_payment.appendChild(awaiting_fieldInfo);

    document.getElementById(`delete-awaiting-field`).addEventListener('click', async function () {
        await deleteSettingsField(awaiting_field.id);
    });

    document.getElementById('save-awaiting-fields-line').addEventListener('click', async function (event) {
        //event.preventDefault(); 
        await saveSettingsField();
    });

    if (awaiting_field.type != '') {
        var product_type = document.getElementById('product_type');
        // Используем switch для установки атрибута selected в зависимости от значения order.status
        product_type.querySelector(`option[value="${awaiting_field.type}"]`).selected = true;
    }

    //document.getElementById(`admin-is-manager-${awaiting_field.user_id}`).addEventListener('change', async function() {                 
    //    await updateAdminRule('MANAGER', this.checked);
    //});
    //})

    setMenuDiv('settings-awaiting-payment');
}

async function deleteSettingsField(product_id) {
    var form = document.getElementById('form-setting-awaiting-field');
    var formData = {};

    formData['product_id'] = product_id

    await updateAwaitingFields('delete', formData);

    await openSettingsFields();
}

async function saveSettingsField() {
    //alert('Не реализованно saveSettingsField()');
    // для сохранения настройки полей 

    // получаем значение полей
    var form = document.getElementById('form-setting-awaiting-field');
    var formData = {};

    console.log('form -> ', form);

    // Получаем все элементы формы
    var elements = form.elements;

    // Проходимся по каждому элементу формы
    for (var i = 0; i < elements.length; i++) {
        var element = elements[i];
        // Проверяем, что элемент - текстовое поле (или другой тип поля ввода, который вам нужен)
        if (['INPUT', 'SELECT'].includes(element.tagName) && element.type !== 'button') {
            // Добавляем значение поля в объект formData, используя имя поля в качестве ключа
            formData[element.name] = element.value;
        }
    }

    // Выводим значения полей в консоль (вы можете сделать что-то еще с этими значениями)
    console.log('formData -> ', formData);

    // отправляем запрос на изменение
    await updateAwaitingFields('update', formData);

    // обновляем данные полей
    await openSettingsFields();
    // возвращаемся
    //setMenuDiv('settings-awaiting-payment');

}

async function getSettingsAPI(type, field) {
    try {
        const response = await fetch(urlTgParams + '/get_settings_API', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })
        });
        const data = await response.json();
        return data.API_order_status; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function openSettingsAPI() {
    // открываем настройку API
    const get_settings_API = await getSettingsAPI();

    const cart_setting_API = document.getElementById('cart-setting-API');
    cart_setting_API.innerHTML = '';

    //awaiting_fields_list.forEach(awaiting_field => {
    const setting_APIInfo = document.createElement('div');
    setting_APIInfo.innerHTML = `
                <form id="form-settings-API" enctype="multipart/form-data">
                    <h2>При создании заказа: </h2>
                    <h4>Ссылка: </h4>
                    <input type="text" name="settings_API_url_create" placeholder="API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.create_order.API}" required>
                    <h4>Заголовок: </h4>
                    <input type="text" name="settings_API_header_create" placeholder="Заголовок API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.create_order.header}" required>
                    <br>
                    <h2>При подтверждении оплаты:</h2>
                    <h4>Ссылка: </h4>
                    <input type="text" name="settings_API_url_pyment" placeholder="API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.pyment_order.API}" required>
                    <h4>Заголовок: </h4>
                    <input type="text" name="settings_API_header_pyment" placeholder="Заголовок API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.pyment_order.header}" required>
                    <br>
                    <h2>При окончании оплаты:</h2   >
                    <h4>Ссылка: </h4>
                    <input type="text" name="settings_API_url_sucsess" placeholder="API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.sucess_pyment.API}" required>
                    <h4>Заголовок: </h4>
                    <input type="text" name="settings_API_header_sucsess" placeholder="Заголовок API куда делать отправлять с запрос о создании заказа" value="${get_settings_API.sucess_pyment.header}" required>
                    <button type="button" id="save-settings-API" class="btn">СОХРАНИТЬ</button>
                </form>
            `;
    cart_setting_API.appendChild(setting_APIInfo);

    document.getElementById(`save-settings-API`).addEventListener('click', async function () {
        await updateSettingsAPI();
        setMenuDiv('settings');
    });

    setMenuDiv('settings-API');
}

async function updateSettingsAPI() {
    var data_API_settings = {};
    var form_settings_API = document.getElementById('form-settings-API');

    // Получаем все элементы формы
    var elements = form_settings_API.elements;

    // Проходимся по каждому элементу формы
    for (var i = 0; i < elements.length; i++) {
        var element = elements[i];
        // Проверяем, что элемент - текстовое поле (или другой тип поля ввода, который вам нужен)
        if (element.tagName === 'INPUT' && element.type !== 'button') {
            // Добавляем значение поля в объект formData, используя имя поля в качестве ключа
            data_API_settings[element.name] = element.value;
        }
    }

    try {
        const response = await fetch(urlTgParams + '/update_settings_API', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, API_settings: data_API_settings })
        });
        const data = await response.json();
        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function openSettingsPyment() {
    // Открываем форму для заполнения данных оплаты
    alert('Не реализованно openSettingsPyment');
}


// ------- Заказы -------
async function getOrders() {
    try {
        const response = await fetch(urlTgParams + '/get_all_orders', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        return data.user_orders; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

const getOrderByNo = (orderNo) => {
    console.log(orders_list);
    return orders_list.find(order => order.no === orderNo);
};

const getOrderDetailsByNo = (orderNo) => {
    console.log(orders_list);
    return orders_list.find(order => order.no === orderNo);
};

const orderContainer = document.getElementById('cart-orders');

function openOrder() {
    alert('Не реализованно openOrder()');
}


function createOrderElement(order) {
    const orderDiv = document.createElement('div');
    orderDiv.classList.add('item');

    const orderInfo = document.createElement('div');
    orderInfo.classList.add('item')
    orderInfo.innerHTML = `
        <div class="item_image">
            <div class="picture_slide_box_catalog"><img height="100%" width="100%"
                    src="Group 32.png" alt="">
                <div class="number_orders"><b>3</b>шт</div>
            </div>
        </div>
        <div class="item_data">
            <p class="item_p margin_p">Заказ: ${order.no}</p>
            <p class="item_p item_status">
                Статус:
                <span class="badge badge_green">${order.status}</span>
            </p>
            <p class="item_p">Создан: ${order.create_dt}</p>
            <a href="#" class="btn btn_inline">отменить</a>
        </div>
    `;
    orderInfo.classList.add('order-info');
    orderDiv.appendChild(orderInfo);

    orderInfo.addEventListener('click', () => {
        createOrderInfo(order);

        setMenuDiv('order');
    });

    return orderDiv;
}


async function addProduktToLine(order_no, product_id) {
    //alert('Не реализованно addProduktToLine()');
    // создаём строку в заказе с определённым товаром
    try {
        const response = await fetch(urlTgParams + '/add_item_to_order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, order_no: order_no, product_id: product_id })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        await renderOrders();
        createOrderElement(getOrderByNo(order_no));
        createOrderInfo(getOrderByNo(order_no));
        // возвращаемся на страницу заказа
        setMenuDiv('order');
        //return data.user_orders; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
    // отправляем на сервер запрос на создание новой строки в заказе 

    // получаем заново заказы
}

async function saveOrderLine(order_no) {
    //alert('Не реализованно saveOrderLine()');
    // для создания строки в заказе без привязки к товару

    // проверяем введённаые данные на валидность
    const form_create_line = document.getElementById('form-create-line');
    const formData_create_line = new FormData(form_create_line);
    var data_create_line = {};

    formData_create_line.forEach((value, key) => {
        data_create_line[key] = value;
    });

    console.log(data_create_line);

    // отправляем запрос на создание строки
    try {
        const response = await fetch(urlTgParams + '/add_line', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: tg_id,
                order_no: order_no,
                product_id: form_create_line.elements['product_id'].value,
                name: data_create_line['product_name'],
                description: data_create_line['product_description'],
                price: getPriceToSend(data_create_line['product_price']),
                quantity: data_create_line['quantity']
            })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        await renderOrders();
        createOrderElement(getOrderByNo(order_no));
        createOrderInfo(getOrderByNo(order_no));
        // возвращаемся на страницу заказа
        setMenuDiv('order');
        //return data.user_orders; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }

    // заново получаем все заказы в базе

    // возвращаемся на карточку товара 
    //setMenuDiv('order');

}

async function createLineNoItem(order_no) {
    const cart_order_edit_line = document.getElementById('cart-order-edit-line');
    cart_order_edit_line.innerHTML = '';

    const lineInfo = document.createElement('div');
    lineInfo.innerHTML = `
                <form id="form-create-line" enctype="multipart/form-data">
                    <h2>${order_no}</h2>
                    <h3>Товар: <p>0</p></h3>
                    <input type="text" name="product_id" placeholder="Номер товара, если нету - 0" value="0" disabled>
                    <br>
                    <br>
                    <h3>Название:</h3>
                    <input type="text" name="product_name" placeholder="Введите название товара ..." required>
                    <br>
                    <h3>Описание:</h3>
                    <input type="text" name="product_description" placeholder="Введите описание товара ..." required>
                    <br>
                    <h3>Цена за штуку:</h3>
                    <input type="text" name="product_price" placeholder="Введите цену товара" required>
                    <br>
                    <h3>Колличество:</h3>
                    <input type="number" name="quantity" min="0" max="10000" step="0.01" value="1" placeholder="от 0 до 10000">
                    <br>
                    <h3>Скидка:</h3>
                    <input type="number" name="discount" min="0" max="100" step="1" value="1" placeholder="от 0 до 100">
                    <br>
                    <button type="button" id="save-order-line" class="btn">СОХРАНИТЬ</button>
                </form>
            `;
    lineInfo.classList.add('order-line');
    cart_order_edit_line.appendChild(lineInfo);

    //cart_order_edit_line.innerHTML += `<button id="save-order-line" class="btn">СОХРАНИТЬ</button>`;

    document.getElementById('save-order-line').addEventListener('click', async function (event) {
        //event.preventDefault(); 
        await saveOrderLine(order_no);
    });

    setMenuDiv('order-edit-line');
}

async function selectItem(order_no) {
    // если мы хотим добавить товар или услугу, то нужна эта функция
    // у нас отурывается форма, где мы можем добавить любой товар или нажать на кнопку добавить ручное
    //   если добавить ручное, то мы открываем форму с пустой строкой, где заполним всё сами

    const products = await fetchProducts();

    const cart_order_add_item = document.getElementById('cart-order-add-item');
    cart_order_add_item.innerHTML = ''; // Очистка содержимого перед добавлением новых товаров

    //order_add_item.innerHTML += `<button id="new-line-not-item" class="btn btnGreen">Добавить строку без товара</button>`;
    
    ///order_add_item.innerHTML += `    
    ///    <div class="tab_title" style="margin-bottom: 5%;">
    ///        <p>Добавить товар к заказу ${order.no}</p>
    ///    </div>
    ///`;


    products.forEach(product => {
        const productElement = document.createElement('div');
        productElement.classList.add('item');
        productElement.setAttribute('id', `product-${product.id}`); // Установка ID для каждой карточки товара
        var price = parseFloat(product.price) / 100;

        productElement.innerHTML = `

            <div class="item_image">
                <div class="picture_slide_box">
                    <img height="100%" width="60%" src=${DomainUrl}${product.media_list[0]}" alt="${product.name}">
                </div>
            </div>
            <div class="item_data">
                <div class="item_meta">
                    <div class="item_prices">
                        <p class="price">${price}&#8381;</p>
                    </div>
                    <div class="item_stock">
                        <span>${product.quantity}</span> шт
                    </div>
                </div>
                <p class="item_title">${product.name}</p>
                <button type="button" class="btn addToCart" id="add-item-to-line-${product.id}"><img width="10px" src="icon/Plus.png" alt=""> Добавить</button>
            </div>
        `;

        cart_order_add_item.appendChild(productElement);

        document.getElementById(`add-item-to-line-${product.id}`).addEventListener('click', async function () {
            await addProduktToLine(order_no, product.id);
        });


    });

    document.getElementById('new-line-not-item').addEventListener('click', async function () {
        await createLineNoItem(order_no);
    });

    setMenuDiv('order-add-item');
}



function createOrderInfo(order) {
    cart_order_div.innerHTML = ''; // Очистка содержимого перед добавлением новых товаров

    const orderDetails = document.createElement('div');
    orderDetails.classList.add('product');

    var awaitingFields = `
            <h3 class="info_goods">Информация о заказе</h3>
        <hr>
        <div class="email_hrefs_box">
            <p>Почта</p>
            <div class="arrow_txt"><img src="icon/Line 15.png" alt="">
                <a href="#">deniska_zhukov_00@inbox.ru</a>
            </div>
        </div>
        <div class="email_hrefs_box midle_margin">
            <p>Телефон</p>
            <div class="arrow_txt"><img src="icon/Line 15.png" alt="">
                <a href="#">+7 (964) 800 81 91</a>
            </div>
        </div>
        <div class="email_hrefs_box addr">
            <p>Адрес доставки</p>
            <div class="arrow_txt"><img src="icon/Line 15.png" alt="">
                <a href="#">г. Санкт-Петербург, Выборгский район, Латышских стрелков, дом 17, кв. 11</a>
            </div>
        </div>

    `;
    console.log(order);
    var additional_fields_list = order.additional_fields;

    for (let key in additional_fields_list) {
        if (additional_fields_list.hasOwnProperty(key)) {
            let additional_fields_data = additional_fields_list[key];
            console.log("Ключ: " + key + ", Значение: " + additional_fields_data);
            awaitingFields += `<p>${additional_fields_data.description}: ${additional_fields_data.value}</p><br>`;
        }
    }

    orderDetails.innerHTML = `
        <div class="order" style="display: flex; flex-direction: column;">
                    <div class="back_ordernum_box">
                        <p>Заказ: <strong>${order.no}</strong></p>
                    </div>  
                    <div class="starus_create_block">
                        <div class="create_elem" style="padding-bottom: 2%;">
                            <p class="left_width">Статус:</p>
                            <p class="date_create">${order.status}</p>
                        </div>
                        <div class="status_elem">
                            <p class="left_width">Выбрать статус:</p>
                            <select id="selectStatusList" class="status_color">
                                <option value="NEW">Новый</option>
                                <option value="REQUIRES_CONFIRM_MENAGER">Ожидает подтверждения менаджера</option>
                                <option value="NEED_PAYMENTS">Ожидает оплаты</option>
                                <option value="PAYMENT_SUCCESS">Оплачен</option>
                                <option value="ASSEMBLING">Собирается</option>
                                <option value="SENT">Отправлен</option>
                                <option value="READY_TO_ISSUDE">Готов к выдаче</option>
                                <option value="COMPLETED">Завершён</option>
                                <option value="CANCEL">Отменён</option>
                            </select>
                        </div>
                        <div class="create_elem" style="padding-bottom: 2%;">
                            <p class="left_width">Создано:</p>
                            <p class="date_create">${order.create_dt}</p>
                        </div>
                        <div class="paid create_elem">
                            <label for="paid">Оплачен:</label>
                            <input type="checkbox" id="is_paid_for" name="is_paid_for" ${order.is_paid_for ? 'checked' : ''}>
                        </div>
                    </div>      
                    <div class="products" style="margin-bottom: 20px;">
                        <h3 class="goods_text">Товары</h3>
                        <hr>

                    </div>
            `;

    console.log(order.lines);
    if (order.lines && order.lines.length > 0) {
        order.lines.forEach(line => {
            const lineItem = document.createElement('div');
            //lineItem.classList.add('order-item');
            lineItem.classList.add('itemInfoPositionOrder');
            lineItem.innerHTML = `
                <div class="left_block_bg_">
                    <img width="100%" height="100%" src="Group 32.png" alt="">
                </div>
                <div class="right_block_txt">
                    <p>ID товара: ${line.item_id}</p>
                    <p>Кол-во:${line.quantity}шт.</p>
                    <p>Стоимость:${getPriceDec(line.price)} ₽</p>
                    <button id="edit-line-${line.id}" class="btn btn_inline" style="margin-bottom: 6%;">Изменить</button>
                </div>   
            `;
            orderDetails.appendChild(lineItem);
        });
    };

    orderDetails.innerHTML += `                        
        <button id="new-item" class="btnAddManager" ">
            <img src="icon/Plus.png">Добавить товар 
        </button>`;


    //orderDetails.addEventListener("mousedown", function(event) {
    //    event.preventDefault();
    //});
    orderDetails.innerHTML += awaitingFields;

    ///orderDetails.innerHTML += `
///
    ///    <div class="fixed_done_manipulator_order" style="display: flex;">
    ///        <img width="30px" src="icon/Ellipse 34.png" class="back___btn " alt="" onclick="setMenuDiv('orders')">
    ///        <button id="send-message-btn" class="middle_add_btn">
    ///            <img width="20px" src="icon/Send.png" alt="">
    ///            Написать клиенту
    ///        </button>
    ///        <img width="30px" style="opacity: 0;" src="icon/Group 46.png" alt="" class="right_arrow_btn">
    ///    </div>
    ///`;

    cart_order_div.appendChild(orderDetails);

    if (order.lines && order.lines.length > 0) {
        order.lines.forEach(line => {
            document.getElementById(`edit-line-${line.id}`).addEventListener('click', async function () {
                await openEditLite(order.no, line);
            });
        });
    }

    ///document.getElementById('issue-invoice').addEventListener('click', async function () {
    ///    alert('Отправка чека уже сделана, когда вы изменили статус. Нужно удалить');
    ///    //await sendIssueInvoice(order.no);
    ///});

    document.getElementById('is_paid_for').addEventListener('click', async function () {
        var is_paid_for = order.is_paid_for ? true : false;
        console.log(order.is_paid_for, is_paid_for);
        if (is_paid_for) {
            is_paid_for = order.is_paid_for == 1;
        }
        is_paid_for = !is_paid_for;
        //is_paid_for = true;
        await sendEditPaidFor(order.no, is_paid_for);
    });

    var selectStatusList = document.getElementById('selectStatusList');
    var orderStatus = order.status;
    if (orderStatus == 'REQUIRES_CONFIRM_MENAGER') {
        var button_issue_invoice = document.getElementById('issue-invoice');
        button_issue_invoice.style.display = 'block';
    }

    // Используем switch для установки атрибута selected в зависимости от значения order.status
    selectStatusList.querySelector(`option[value="${order.status}"]`).selected = true;

    document.getElementById('new-item').addEventListener('click', async function () {
        await selectItem(order.no);
    });

    document.getElementById('send-message-btn').addEventListener('click', async function () {
        await render_message_form(order);
        document.getElementById('cart-order-message').style.display = 'flex';
        setMenuDiv('order-send-message');
        console.log('setMenuDiv --> send-message-btn --> ВЫЗВАЛСЯ')
    });

    const select_status_list = orderDetails.querySelector('#selectStatusList');

    // Добавляем обработчик события change
    select_status_list.addEventListener('change', function (event) {
        const selectedValue = event.target.value;
        // Выполняем запрос с выбранным значением
        //makeRequest(selectedValue);
        console.log(selectedValue);
        // нужно отправить изменения на сервер
        updateOrderStatus(order.no, selectedValue);
        if (selectedValue == 'REQUIRES_CONFIRM_MENAGER') {
            var button_issue_invoice = document.getElementById('issue-invoice');
            button_issue_invoice.style.display = 'block';
        }
        // Получаем обновление данных
    });

    setMenuDiv('order');
}

async function sendEditPaidFor(order_no, is_paid_for) {
    try {
        const currentPageUrl = urlTgParams + '/edit_paid_for';
        const response = await fetch(currentPageUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, order_no: order_no, is_paid_for: is_paid_for })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        await renderOrders();
        createOrderElement(getOrderByNo(order_no));
        createOrderInfo(getOrderByNo(order_no));

        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function render_message_form(order) {
    console.log('render_message_form --> ВЫЗВАЛСЯ')
    const message_form = document.getElementById('cart-order-message');
    message_form.innerHTML = '';

    //const message_form_div = document.createElement('div');
    //message_form_div.classList.add('modal-content');
    message_form.innerHTML = `

        <form id="form-message-order" enctype="multipart/form-data" class="modal-content" style="height: 100%;">
            <h3 class="headerSettings">Сообщение по заказу: <p style="margin: 0 2%; font-weight: 600;">${order.no}</p></h3>
            <div class="nameInput">
                <img class="icon_arrow" src="icon/Line 15.png" alt="">
                <label for="min-order">Текст сообщения</label>
            </div>
            <div class="textareaInput">
                <textarea class="inputCreateStyle" name="order_no" id="message_text_order" placeholder="Введите текст сообщения" rows="8"></textarea>
            </div>
            <div class="fixed_done_manipulator_order" style="display: flex;">
                <img width="30px" src="icon/Ellipse 34.png" class="back___btn " alt="" onclick="setMenuDiv('order')">
                <button id="send-message" class="middle_add_btn">
                    <img width="20px" src="icon/Send.png" alt="">
                    Отправить
                </button>
                <img width="30px" style="opacity: 0;" src="icon/Group 46.png" alt="" class="right_arrow_btn">
            </div>
        </form>

    `;

    //message_form.appendChild(message_form_div);
    ////document.getElementById('order-send-message').appendChild(message_form);

    document.getElementById('send-message').addEventListener('click', async function () {
        const form_message_order = document.getElementById("form-message-order");
        //const formData = new FormData(form_message_order);
        var message_text = form_message_order.elements['message_text_order'].value;
        await sendOrderMessage(order.no, message_text);
    });
}

async function sendOrderMessage(order_no, message) {
    try {
        const currentPageUrl = urlTgParams + '/send_message';
        const response = await fetch(currentPageUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, order_no: order_no, message: message })
        });
        const data = await response.json();
        setMenuDiv('order');

        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function openEditLite(order_no, line) {
    // открываем форму для редактирования строки
    const cart_order_edit_line = document.getElementById('cart-order-edit-line');
    cart_order_edit_line.innerHTML = '';

    const lineInfo = document.createElement('div');
    console.log('line', line);
    lineInfo.innerHTML = `
                <form id="form-create-line" enctype="multipart/form-data">
                    <h2>${order_no}</h2>
                    <h3>Строка: <p>0</p></h3>
                    <input type="text" name="line_id" placeholder="Номер строки" value="${line.id}" disabled>
                    <br>
                    <br>
                    <h3>Название:</h3>
                    <input type="text" name="product_name" placeholder="Введите название товара ..." value="${line.name}" required>
                    <br>
                    <h3>Описание:</h3>
                    <input type="text" name="product_description" placeholder="Введите описание товара ..." value="${line.description}" required>
                    <br>
                    <h3>Цена за штуку:</h3>
                    <input type="text" name="product_price" placeholder="Введите цену товара" step="0.01" value="${getPriceDec(line.price)}" required>
                    <br>
                    <h3>Колличество:</h3>
                    <input type="number" name="quantity" min="0" max="10000" step="1" value="${line.quantity}" placeholder="от 0 до 10000">
                    <br>
                    <button type="button" id="save-edit-line" class="btn">СОХРАНИТЬ</button>
                    <button type="button" id="delete-edit-line" class="btn">УДАЛИТЬ</button>
                </form>
            `;
    lineInfo.classList.add('order-line');
    cart_order_edit_line.appendChild(lineInfo);

    //cart_order_edit_line.innerHTML += `<button id="save-order-line" class="btn">СОХРАНИТЬ</button>`;

    document.getElementById('save-edit-line').addEventListener('click', async function (event) {
        //event.preventDefault(); 
        await saveEditLine(order_no);
    });

    document.getElementById('delete-edit-line').addEventListener('click', async function (event) {
        //event.preventDefault(); 
        await deleteEditLine(line.id, order_no);
    });

    setMenuDiv('order-edit-line');
}

async function saveEditLine(order_no) {
    const form_create_line = document.getElementById('form-create-line');
    const formData_create_line = new FormData(form_create_line);
    var data_create_line = {};

    formData_create_line.forEach((value, key) => {
        data_create_line[key] = value;
    });

    console.log(data_create_line);

    // отправляем запрос на создание строки
    //try {
    const response = await fetch(urlTgParams + '/edit_line', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            user_id: tg_id,
            line_id: form_create_line.elements['line_id'].value,
            name: data_create_line['product_name'],
            description: data_create_line['product_description'],
            price: getPriceToSend(data_create_line['product_price']),
            quantity: data_create_line['quantity']
        })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
    });
    const data = await response.json();
    await renderOrders();
    createOrderElement(getOrderByNo(order_no));
    createOrderInfo(getOrderByNo(order_no));
    // возвращаемся на страницу заказа
    setMenuDiv('order');
    //return data.user_orders; // Предполагается, что ваш API возвращает массив товаров
    //} catch (error) {
    //    console.error('Ошибка при получении данных о товарах:', error);
    //    return [];
    //}
}

async function deleteEditLine(line_id, order_no) {
    const response = await fetch(urlTgParams + '/delete_line', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            user_id: tg_id,
            line_id: line_id
        })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
    });

    await renderOrders();
    createOrderElement(getOrderByNo(order_no));
    createOrderInfo(getOrderByNo(order_no));
    setMenuDiv('order');
}

async function sendIssueInvoice(order_no) {
    const response = await fetch(urlTgParams + '/send_issue_invoice', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ user_id: tg_id, order_no: order_no })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
    });
    const data = await response.json();
    updateOrderStatus(order_no, 'NEED_PAYMENTS');
    await renderOrders();
    createOrderElement(getOrderByNo(order_no));
    createOrderInfo(getOrderByNo(order_no));
    return data.success; // Предполагается, что ваш API возвращает массив товаров
}

async function updateOrderStatus(order_no, status) {
    //alert(`Не реализованно updateAdminRule(${rule}, ${should_add_it})`); 
    try {
        const response = await fetch(urlTgParams + '/update_order_status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, order_no: order_no, status: status })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        renderOrders();
        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

function openEditOrder(orderNo) {
    var order = getOrderDetailsByNo(orderNo);

    setMenuDiv('order-setting');
}

async function renderOrders() {
    orders_list = await getOrders();
    console.log(orders_list);
    orderContainer.innerHTML = '';
    orders_list.forEach(order => {
        const orderElement = createOrderElement(order);
        orderContainer.appendChild(orderElement);
    });
}

var orders_list;

renderOrders();


// ------- Товары -------
const getProductByNo = (product_no) => {
    console.log(products);
    var product = products.find(product => product.id === product_no);
    if (!product) {
        product = {
            id: '0',
            media_list: [''],
            name: '',
            description: '',
            price: 0,
            quantity: 0,
            discount: 0,
            requires_confirm_menager: false,
            activ: true
        }
    }
    return product;
};

async function fetchProducts() {
    try {
        const currentPageUrl = urlTgParams + '/get_all_items';
        const response = await fetch(currentPageUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })//tg.initDataUnsafe.user.id }) // передача текста 'qwerqwqwe'
        });
        const data = await response.json();
        return data.items; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function saveProduct(order_no) {
    //alert('Не реализованно saveProduct()');

    //const formData = new FormData(

    const form_product = document.getElementById("form-edit-product");
    const formData = new FormData(form_product);
    //const fileInput = document.querySelector('input[type="file"]');
    const fileInputs = document.querySelectorAll('input[type="file"]');
    // Перебираем все выбранные файлы и добавляем их в formData
    fileInputs.forEach((fileInput, index) => {
        for (const file of fileInput.files) {
            formData.append('files[]', file);
            console.log(fileInput.files);
        }
    });
    var product_id = form_product.elements['product_id'].value;
    formData.append('product_id', product_id);
    formData.append('media_list', form_product.elements['media_list'].value);
    //formData['product_activ'] = 'ok'//form_product.elements['product_activ'].value == 'on';
    formData.append('user_id', tg_id);

    const response = await fetch(urlTgParams + '/save_item', {
        method: 'POST',
        body: formData
    });

    // Обработка ответа
    const data = await response.json();
    //return data.success;
    // для создания строки в заказе без привязки к товару

    // проверяем введённаые данные на валидность

    // отправляем запрос на создание строки

    // заново получаем все заказы в базе

    // возвращаемся на карточку товара 
    setMenuDiv('items');

}

function getNormalPrice(price, discount) {
    const discountedPrice = price - (price * discount / 100);
    const endPrice = discountedPrice;

    return endPrice.toFixed(2); // Округляем до двух знаков после запятой
}

function getPriceDec(price) {
    return price / 100;
}

function getPriceToSend(price) {
    return Math.round(price * 100);
}

//Модалка по созданию нового товара
async function openEditProductCart(product_no) {
    const cart_item = document.getElementById('cart-item');
    cart_item.innerHTML = '';

    const product_by_no = getProductByNo(product_no);
    console.log(product_by_no);

    const productInfo = document.createElement('div');
    productInfo.innerHTML = `
        <div id="myModal" class="modal">
            <div class="modal-content" style="height: 100%;">
                <div class="container">

                    <div class="product-id">
                        <h2 class="headerSettings">Товар:
                            <span style="font-weight: 600;">${product_by_no.id}</span>
                        </h2>
                    </div>
                    <form id="form-edit-product" enctype="multipart/form-data">
                        <div class="photo-upload-container">
                            <div class="photo-upload">
                            <input class="active-file" type="file" name="photos" id="fileInput_0" data-id="0" multiple>    
                            <span>+</span>
                            </div>
                            <span>Добавить фото</span>
                            <div id="error-message" style="color: red;"></div>
                        </div>
                        <div id="photo-previews"></div>

                        <div class="containerNewProduct">

                            <div class="nameInput">
                                <img class="icon_arrow" src="../css/icon/Line 15.png" alt="">
                                <label for="min-order">Номер товара</label>
                            </div>
                            <div class="textareaInput">
                                <input name="product_id" class="inputCreateStyle" type="text" value="${product_by_no.id}" placeholder="Введите номер товара" disabled>
                            </div>
                            <div class="textareaInput">
                                <input name="media_list class="inputCreateStyle" type="text" value="${product_by_no.media_list[0]}" disabled placeholder="Введите название товара">
                            </div>

                            <div class="nameInput">
                                <img class="icon_arrow" src="../css/icon/Line 15.png" alt="">
                                <label for="min-order">Название</label>
                            </div>
                            <div class="textareaInput">
                                <input name="product_name" class="inputCreateStyle" type="text" value="${product_by_no.name}" required placeholder="Введите название товара">
                            </div>

                            <div
                                style=" max-width: 100%; display: flex; flex-direction: row; justify-content: space-between; margin: 3% 0;">
                                <div>
                                    <div class="nameInput">
                                        <img class="icon_arrow" src="../css/icon/Line 15.png" alt="">
                                        <label for="min-order">Цена за штуку</label>
                                    </div>
                                    <div class="textareaInput">
                                        <input name="product_price" min="0" max="100000" style="width: 80%;" class="inputCreateStyleMin" type="number" value="${product_by_no.price / 100}" placeholder="&#8381">
                                    </div>
                                </div>

                                <div>
                                    <div class="nameInput">
                                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                                        <label for="min-order">Скидка</label>
                                    </div>
                                    <div class="textareaInput">
                                        <input style="width: 80%;" class="inputCreateStyleMin" type="number" name="discount" min="0" max="100" step="1" value="${product_by_no.discount}" placeholder="%">
                                    </div>
                                </div>

                                <div class="totalStyle">Итог: <p>${(product_by_no.quantity * product_by_no.discount) / 100}</p>
                                </div>
                            </div>

                            <div class="nameInput">
                                <img class="icon_arrow" src="icon/Line 15.png" alt="">
                                <label for="min-order">Количество</label>
                            </div>
                            <div class="textareaInput">
                                <input name="quantity" min="0" max="10000" step="1" class="inputCreateStyle" type="number" id="quantity" value="${product_by_no.quantity}" placeholder="Количество товара">
                            </div>
                            <div style="margin: 3% 0;">
                                <div class="nameInput">
                                    <img class="icon_arrow" src="icon/Line 15.png" alt="" style="margin-left: 2%">
                                    <label for="min-order">Подтверждение менеджера</label>
                                </div>
                                <div class="nameInput">
                                    <input type="checkbox" name="product_requires_manager" ${product_by_no.requires_confirm_menager ? 'checked' : ''}>
                                </div>
                            </div>

                            <div style="margin: 3% 0;">
                                <div class="nameInput">
                                    <img class="icon_arrow" src="icon/Line 15.png" alt="" style="margin-left: 2%">
                                    <label for="min-order">Активен</label>
                                </div>
                                <div class="nameInput">
                                    <input type="checkbox" name="product_activ" ${product_by_no.activ ? 'checked' : ''}>
                                </div>
                            </div>

                            <div class="nameInput">
                                <img class="icon_arrow" src="icon/Line 15.png" alt="">
                                <label for="min-order">Описание</label>
                            </div>
                            <div class="textareaInput">
                                <textarea name="product_description" class="inputCreateStyle" type="text" value="${product_by_no.description}" required placeholder="Введите описание товара" rows="4"></textarea>
                            </div>
                        </div>
                    </form>

                    <div class="fixed_done_manipulator" style="padding-bottom: 4%;">
                        <img width="30px" src="icon/Ellipse 34.png" href="javascript:void(0);" data-tab="main"
                            class="delete-btn" style="background-color: white;" alt="">

                        <button id="save-order-line" class="btn" style="margin: 0; padding: 2% 15%;" onclick="setMenuDiv('items')">
                            <img width="20px" src="icon/Save file.png" alt="">
                            Сохранить
                        </button>

                        <img width="30px" src="icon/Bin.png" alt="" class="right_arrow_btn">

                    </div>
                </div>

            </div>

        </div>
            `;
    productInfo.classList.add('order-line');
    cart_item.appendChild(productInfo);

    const photoPreviewsContainer = document.getElementById('photo-previews');

    // Очистить контейнер с превью перед загрузкой новых изображений
    photoPreviewsContainer.innerHTML = '';

    // Перебрать каждое изображение из списка медиа
    product_by_no.media_list.forEach(media => {
        // Создать тег <img> для каждого изображения и добавить его в контейнер с превью
        const img = document.createElement('img');
        img.src = DomainUrl + media; // Путь к изображению
        img.alt = 'Product Image';
        img.style.maxWidth = '200px'; // Максимальная ширина 100 пикселей
        img.style.maxHeight = '200px'; // Максимальная высота 100 пикселей
        img.style.width = 'auto'; // Автоматический расчет ширины для сохранения пропорций
        img.style.height = 'auto'; // Автоматический расчет высоты для сохранения пропорций
        photoPreviewsContainer.appendChild(img);
    });

    // ЗАГРУЗКА ФОТО
    // Функция для обновления превью фотографий
    function updatePhotoPreviews() {
        const photoPreviews = document.getElementById('photo-previews');
        photoPreviews.innerHTML = '';
        const fileInputs = document.querySelectorAll('input[type="file"]');
        // Перебираем все выбранные файлы и добавляем их в formData
        var id_photo = 0;
        fileInputs.forEach((fileInput, index) => {
            for (const file of fileInput.files) {
                //formData.append('files[]', file);
                const photoPreview = document.createElement('img');
                photoPreview.src = URL.createObjectURL(file);
                photoPreview.style.maxWidth = '100px';
                photoPreview.style.maxHeight = '100px';

                // Добавляем кнопку удаления для каждой фотографии
                const deleteButton = document.createElement('button');
                deleteButton.classList.add('btn');
                deleteButton.textContent = 'Удалить';
                deleteButton.type = 'button';
                deleteButton.id = `deleteButton-${id_photo}`;

                const previewContainer = document.createElement('div');
                previewContainer.appendChild(photoPreview);
                previewContainer.appendChild(deleteButton);
                photoPreviews.appendChild(previewContainer);

                id_photo += 1;
            }
        });
        /*
        const photos = document.getElementById('fileInput_0').files;
        console.log('photos', photos);

        for (let i = 0; i < photos.length; i++) {
            const photoPreview = document.createElement('img');
            photoPreview.src = URL.createObjectURL(photos[i]);
            photoPreview.style.maxWidth = '100px';
            photoPreview.style.maxHeight = '100px';

            // Добавляем кнопку удаления для каждой фотографии
            const deleteButton = document.createElement('button');
            deleteButton.classList.add('btn');
            deleteButton.textContent = 'Удалить';
            deleteButton.type = 'button';
            deleteButton.id = `deleteButton-${i}`;

            const previewContainer = document.createElement('div');
            previewContainer.appendChild(photoPreview);
            previewContainer.appendChild(deleteButton);
            photoPreviews.appendChild(previewContainer);
        }
        */

        photoPreviews.innerHTML += '<p><span style="color:red;">После сохранения старые фото будут затёрты</span></p>';

        //for (let i = 0; i < photos.length; i++) {
        id_photo = 0;
        fileInputs.forEach((fileInput, index) => {
            for (const file of fileInput.files) {
                console.log(`deleteButton-${id_photo}`);
                document.getElementById(`deleteButton-${id_photo}`).addEventListener('click', function (event) {
                    //alert('Удаление 1');
                    const photoPreview = this.parentNode;

                    // Получаем индекс фотографии в списке
                    const indexToRemove = Array.from(photoPreviews.children).indexOf(photoPreview);
                    console.log(photoPreviews.children, photoPreview, indexToRemove);

                    fileInput.parentNode.removeChild(fileInput);
                    updatePhotoPreviews();

                });

                id_photo += 1;
            }
        });
    }

    function add_input_photo() {
        const photos_div = document.getElementById(`photos_div`);
        var elements = photos_div.getElementsByTagName('*');

        // Пройти по каждому элементу и добавить атрибут disabled
        var last_id = 0;
        for (var i = 0; i < elements.length; i++) {
            //elements[i].disabled = true;
            elements[i].style.display = 'none';
            console.log(elements[i].id);
            let lastIndex = elements[i].id.lastIndexOf("_"); // Получаем индекс последнего символа "_"
            last_id = parseInt(elements[i].id.substring(lastIndex + 1)); // Получаем подстроку после последнего "_" и преобразуем ее в число
        }

        var input = document.createElement('input');
        var next_id = last_id + 1;

        // Установка атрибутов для нового элемента input
        input.setAttribute('class', 'active-file');
        input.setAttribute('type', 'file');
        input.setAttribute('name', 'photos_' + next_id);
        input.setAttribute('id', 'fileInput_' + next_id);
        input.setAttribute('data-id', '0');
        input.setAttribute('multiple', '');

        // Добавление элемента input на страницу (например, в body)
        document.body.appendChild(input);
        //photos_div.innerHTML += `<input class="active-file" type="file" name="photos_${i}" id="fileInput_${i}" data-id="0" multiple>`
        photos_div.appendChild(input);

        document.getElementById(`fileInput_${next_id}`).addEventListener('change', function (event) {
            updatePhotoPreviews();
            add_input_photo();
        });
    }

    // Обновляем превью фотографий при выборе файлов
    document.getElementById('fileInput_0').addEventListener('change', function (event) {
        updatePhotoPreviews();
        add_input_photo();
        //previewContainer.appendChild(photoPreview);
    });
    /*
    // Обработчик для кнопки сохранения
    document.getElementById('save-order-line').addEventListener('click', function () {
        // Добавьте здесь код для отправки данных формы, например, AJAX запрос
        // Для примера, пока выведите в консоль данные формы
        const formData = new FormData(document.getElementById('form-edit-product'));
        for (const pair of formData.entries()) {
            console.log(pair[0] + ': ' + pair[1]);
        }
    });
    */


    //cart_item.innerHTML += `<button id="save-order-line" class="btn">СОХРАНИТЬ</button>`;

    document.getElementById('save-order-line').addEventListener('click', async function (event) {
        //event.preventDefault(); 
        await saveProduct(product_no);

        await renderProducts();

        //setMenuDiv('item');
    });

    const form = document.getElementById('form-edit-product');
    const priceInput = form.querySelector('input[name="product_price"]');
    const discountInput = form.querySelector('input[name="discount"]');
    const endPriceInput = form.querySelector('input[name="product_end_price"]');

    // Функция для обновления итоговой цены
    function updateEndPrice() {
        const price = parseFloat(priceInput.value);
        const discount = parseFloat(discountInput.value);

        ///endPriceInput.value = getNormalPrice(price, discount); //endPrice.toFixed(2); // Округляем до двух знаков после запятой
    }

    // Обработчики событий для изменения цены и скидки
    priceInput.addEventListener('input', updateEndPrice);
    discountInput.addEventListener('input', updateEndPrice);

    updateEndPrice();

    setMenuDiv('item');
}

async function renderProducts() {
    products = await fetchProducts();

    const cart_items_main = document.getElementById('cart-items');
    //cart_items_main.innerHTML = `
    //            <button id="create_product" class="btn">ДОБАВИТЬ НОВЫЙ</button>
    //        `; // Очистка содержимого перед добавлением новых товаров

    products.forEach(product => {
        const productElement = document.createElement('div');
        productElement.classList.add('item');
        productElement.setAttribute('id', `product-${product.id}`); // Установка ID для каждой карточки товара
        var price = parseFloat(product.price) / 100;

        productElement.innerHTML = `
            <div class="carousel-container item_image">
                <div id="carousel-slide-${product.id}" class="carousel-slide picture_slide_box">
                    <img height="100%" width="60%" src="${DomainUrl}${product.media_list[0]}" alt="${product.name}" class="carousel-image">
                </div>
                <button id="prevBtn-${product.id}" class="prevBtn">&#10094;</button>
                <button id="nextBtn-${product.id}" class="nextBtn">&#10095;</button>
            </div>

            <div class="item_data">
                <div class="item_meta">
                    <div class="item_prices">
                        <p class="price">${getPriceDec(getNormalPrice(product.price, product.discount))} &#8381;</p>
                        <p class="old_price">${getPriceDec(product.price)} &#8381;</p>
                    </div>
                    <div class="item_stock">
                        <span>${product.quantity}</span> шт
                    </div>
                </div>
                <p class="item_title">${product.name}</p>
                <button class="btn addToCart" id="edit-product-${product.id}"><img width="10px" src="../css/icon/Plus.png" alt=""> Изменить</button>
            </div>
        `;

        cart_items_main.appendChild(productElement);

        document.getElementById(`edit-product-${product.id}`).addEventListener('click', async function () {
            await openEditProductCart(product.id);
        });

        const carouselSlide = document.getElementById(`carousel-slide-${product.id}`);
        const prevBtn = document.getElementById(`prevBtn-${product.id}`);
        const nextBtn = document.getElementById(`nextBtn-${product.id}`);

        let counter = 0;

        // Функция для загрузки изображений в карусель
        function loadImages() {
            carouselSlide.innerHTML = '';
            product.media_list.forEach((image, index) => {
                const img = document.createElement('img');
                img.src = DomainUrl + image;
                img.alt = product.name;
                img.style.maxWidth = '100%';
                img.style.height = '100%';
                img.classList.add('carousel-image');
                if (index === counter) {
                    img.classList.add('active');
                }
                carouselSlide.appendChild(img);
            });
        }

        // Загрузка изображений при загрузке страницы
        loadImages();

        // Обработчики для кнопок "Предыдущее" и "Следующее"
        prevBtn.addEventListener('click', () => {
            counter--;
            if (counter < 0) {
                counter = product.media_list.length - 1;
            }
            slideImage();
        });

        nextBtn.addEventListener('click', () => {
            counter++;
            if (counter >= product.media_list.length) {
                counter = 0;
            }
            slideImage();
        });

        // Функция для плавного перемещения изображений
        function slideImage() {
            const imgWidth = carouselSlide.querySelector('.carousel-image').clientWidth;
            carouselSlide.style.transform = `translateX(-${counter * imgWidth}px)`;
        }
    });

    document.getElementById(`create_product`).addEventListener('click', async function () {
        await openEditProductCart(0);
    });
}

var products;

renderProducts();

// страничка для открытия формы с настройкой параметров сайта
async function openSettingsSite() {
    const settings_site = await getSettingsSite();

    const cart_setting_site = document.getElementById('cart-setting-site');
    cart_setting_site.innerHTML = '';

    //awaiting_fields_list.forEach(awaiting_field => {
    const setting_SiteInfo = document.createElement('div');
    setting_SiteInfo.innerHTML = `
            <form id="form-settings-site" enctype="multipart/form-data">
                <h2 class="headerSettings">Настройка сайта</h2>
                <div style="margin-bottom: 20px;">
                    <div class="nameInput">
                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                        <label for="min-order">Минимальная сумма заказа</label>
                    </div>
                    <div class="textareaInput">
                        <label for="min-order">Не меньше:</label>
                        <input type="number" id="min-order" value="${settings_site.min_amount}"
                            style="width: 40%; padding: 3px 5px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px;">
                    </div>
                </div>
                <div style="margin-bottom: 20px;">
                    <div class="nameInput">
                        <img class="icon_arrow" src="icon/Line 15.png" alt="">
                        <label for="payment-token">Токен оплаты</label>
                    </div>
                    <div class="textareaInput">
                        <textarea id="payment-token"
                            style="width: 91%; padding: 10px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px; color: #acacac; height: 100px;"
                            placeholder="Токен оплаты" value="${settings_site.PAYMENTS_TOKEN}"></textarea>
                    </div>
                </div>
                <button id="save-settings-site" class="btn btnGreen">Сохранить</button>
            </form>
        `;
    cart_setting_site.appendChild(setting_SiteInfo);

    document.getElementById(`save-settings-site`).addEventListener('click', async function () {
        await updateSettingsSite();
        setMenuDiv('settings');
    });

    setMenuDiv('settings-site');
}

async function getSettingsSite() {
    try {
        const response = await fetch(urlTgParams + '/get_settings_site_all', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id })
        });
        const data = await response.json();
        return data.settings_site; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

async function updateSettingsSite() {
    var data_site_settings = {};
    var form_settings_site = document.getElementById('form-settings-site');

    // Получаем все элементы формы
    var elements = form_settings_site.elements;

    // Проходимся по каждому элементу формы
    for (var i = 0; i < elements.length; i++) {
        var element = elements[i];
        // Проверяем, что элемент - текстовое поле (или другой тип поля ввода, который вам нужен)
        if (element.tagName === 'INPUT' && element.type !== 'button') {
            // Добавляем значение поля в объект formData, используя имя поля в качестве ключа
            data_site_settings[element.name] = element.value;
        }
    }

    try {
        const response = await fetch(urlTgParams + '/update_settings_site', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ user_id: tg_id, site_settings: data_site_settings })
        });
        const data = await response.json();
        return data.success; // Предполагается, что ваш API возвращает массив товаров
    } catch (error) {
        console.error('Ошибка при получении данных о товарах:', error);
        return [];
    }
}

//добавление менеджера модалка
const addManagerButton = document.getElementById('add-manager-button');
const addManagerForm = document.getElementById('add-manager-form');
const cancelButton = document.getElementById('cancel');

addManagerButton.addEventListener('click', () => {
    addManagerForm.style.display = 'flex';
});

cancelButton.addEventListener('click', () => {
    addManagerForm.style.display = 'none';
});