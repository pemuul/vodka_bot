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



const tg_id = tg.initDataUnsafe.user && tg.initDataUnsafe.user.id ? tg.initDataUnsafe.user.id : 1001;
console.log(tg_id);

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