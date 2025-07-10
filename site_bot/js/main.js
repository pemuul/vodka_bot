let tg = window.Telegram.WebApp;
tg.expand();

const urlTgParams = 'https://designer-tg-bot.ru/gAAAAABmECxzjzjd693OWoAgJrRP6u-SwQ9-FOnyGDRHuBrHnIr4lNbQ4kjeEP4cN33Z9BDdQX282j4dQiPu7roVUM9oPZSXoI_SuMJ8zXjiGO_a_KaxXyzGfOS516uEkUQCg8AEgPgn'
const DomainUrl = 'https://designer-tg-bot.ru/';



const tg_id = tg.initDataUnsafe.user && tg.initDataUnsafe.user.id ? tg.initDataUnsafe.user.id : 1001;
console.log(tg_id);

jQuery(function($) {
    $(document).ready(function() {
        $('.catalog_item').css('height', $(window).height() - 90);

        $(document).on('click', '.openTab', function() {
            var thisTab = $(this).data('tab');
            var thisTabObject = $('.tab.tab_' + thisTab);
            if (!thisTabObject) {
                return false;
            }
            $('.tab').removeClass('tab_active');
            thisTabObject.addClass('tab_active');
            $('ul').find('li').removeClass('active');
            $(this).parent().addClass('active');
            return false;
        });

        $(document).on('click', '.openProduct', function() {
            $('.tab').removeClass('tab_active');
            $('.tab_product').addClass('tab_active');
            return false;
        });

        $(document).on('click', '.item_gradient', function() {
            $(this).parent().parent().addClass('open');
            $(this).remove();
            return false;
        });

        // Новый код jQuery для обработки кликов по элементам .item
        $(document).on('click', '.item_length .item', function() {
            $('.tab_orders').hide();
            $('.orders_open_window').show();
        });

        // Обработка клика по кнопке back___btn
        $(document).on('click', '.back___btn', function() {
            $('.orders_open_window').hide();
            $('.tab_orders').show();
            $('.fixed_done_manipulator_order').hide();
            return false;
        });
    });
});



// modal
const modal = document.getElementById('myModal')
const closeModal = document.querySelector('.delete-btn')

function
openModal() {
    modal.style.display = 'flex'
}

window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = 'none'
        }
    }
    /* 
    closeModal.onclick = function () {
        modal.style.display = 'none'
    } */

// calc
let minus = document.querySelector('.white_min')
let plus = document.querySelector('.white_pl')
let main_goods = document.querySelectorAll(".openProduct")
let done_modal = document.querySelector('.contaienr')
let middle_add_btn = document.querySelector('.middle_add_btn')
let quantity_goods_btn = document.querySelector('.quantity_goods')
let num_goods_add_num = document.querySelector('.num_goods_add')
let left_back = document.querySelector('.left_back')
let fixed_done_manipulator = document.querySelector('.fixed_done_manipulator')

middle_add_btn.onclick = () => {
    middle_add_btn.style.display = "none"
    quantity_goods_btn.style.display = "flex"
}

plus.onclick = () => {
    num_goods_add_num.innerHTML++
}

minus.onclick = () => {
    num_goods_add_num.innerHTML--
        if (num_goods_add_num.innerHTML <= 0) {
            num_goods_add_num.innerHTML = 1
        }
    console.log('click');
}

left_back.onclick = () => {
    done_modal.style.display = "block"
    fixed_done_manipulator.style.display = "none"
}
main_goods.forEach(btn => {
    btn.onclick = () => {
        done_modal.style.display = "none"
        fixed_done_manipulator.style.display = "flex"

    }
})



var swiper = new Swiper(".mySwiper", {
    navigation: {
        nextEl: ".swiper-button-next",
        prevEl: ".swiper-button-prev",
    },
});




let catalog_item = document.querySelectorAll('.item_length .item')
let num_goods = document.querySelector('.num_goods')

num_goods.innerHTML = catalog_item.length
let items_counter = document.querySelectorAll('.item_controls .item_q');
let totalPriceElement = document.querySelector('.result_price span#total-price');
let res_old_price = document.querySelector('.res_old_price');

// Функция для форматирования чисел в формат российского ценника
function formatPrice(price) {
    return price.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ' ').replace('.', ',');
}

function updateTotalPrice() {
    let totalPrice = 0;
    document.querySelectorAll('.catalog_cart .item_data').forEach(itemData => {
        const priceElement = itemData.querySelector('.price');
        const price = parseFloat(priceElement.getAttribute('data-price'));
        const quantity = parseInt(itemData.querySelector('input').value);
        totalPrice += price * quantity;
    });

    // Обновление totalPriceElement
    totalPriceElement.textContent = formatPrice(totalPrice);

    // Обновление res_old_price
    const additionalAmount = 2000;
    const totalWithAdditional = totalPrice + additionalAmount;
    res_old_price.textContent = formatPrice(totalWithAdditional);
}

items_counter.forEach(item => {
    const minusButton = item.querySelector('.item_qm');
    const plusButton = item.querySelector('.item_qp');
    const input = item.querySelector('input');

    minusButton.addEventListener('click', () => {
        input.value = parseInt(input.value) - 1;
        if (input.value <= 0) {
            input.value = 1;
        }
        updateTotalPrice();
    });

    plusButton.addEventListener('click', () => {
        input.value = parseInt(input.value) + 1;
        updateTotalPrice();
    });
});

// Initial calculation of the total price
updateTotalPrice();




let items_open_ = document.querySelectorAll('.item_length .item')
let orders_open_window = document.querySelector('.orders_open_window')
let monipulator_mod = document.querySelector('.fixed_done_manipulator_order')
let back___btn = document.querySelectorAll('.back___btn')
items_open_.forEach(item => {
    item.onclick = () => {
        done_modal.style.display = "none"
        monipulator_mod.style.display = "flex"
    }
});
back___btn.forEach(btn => {

    btn.onclick = () => {
        done_modal.style.display = "block"

        monipulator_mod.style.display = "none"

    }
});
console.log(items_open_);






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