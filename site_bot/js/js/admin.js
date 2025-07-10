let tg = window.Telegram.WebApp;
tg.expand();

jQuery(function ($) {
  $(document).ready(function () {
    $(".catalog_item").css("height", $(window).height() - 90);
    
    $(document).on("click", ".openTab", function () {
      var thisTab = $(this).data("tab");
      var thisTabObject = $(".tab.tab_" + thisTab);
      if (!thisTabObject) {
        return false;
      }
      $(".tab").removeClass("tab_active");
      thisTabObject.addClass("tab_active");
      $("ul").find("li").removeClass("active");
      $(this).parent().addClass("active");
      return false;
    });

    $(document).on("click", ".openProduct", function () {
      $(".tab").removeClass("tab_active");
      $(".tab_product").addClass("tab_active");
      return false;
    });

    $(document).on("click", ".item_gradient", function () {
      $(this).parent().parent().addClass("open");
      $(this).remove();
      return false;
    });

    // Новый код jQuery для обработки кликов по элементам .item
    $(document).on("click", ".item_length .item", function () {
        $(".tab").removeClass("tab_active");
      $(".orders_open_window").show();
      $(".navig").hide()
    });
    // Обработка клика по кнопке back___btn
    $(document).on("click", ".back___btn", function () {
        $(".navig").show()
        $(".tab_orders").addClass("tab_active");
      $(".orders_open_window").hide();
      $(".fixed_done_manipulator_order").hide();
      return false;
    });
    $(document).on("click", ".managers", function () {
      $(".tab").removeClass("tab_active");
      $(".apspd").addClass("tab_active");
      $(".fixed_done_manipulators").show();
      return false;
    });
    $(document).on("click", ".fields", function () {
      $(".tab").removeClass("tab_active");
      $(".zcx").addClass("tab_active");
      $(".fixed_done_manipulators").show();
      return false;
    });
    $(document).on("click", ".settings", function () {
      $(".tab").removeClass("tab_active");
      $(".sad").addClass("tab_active");
      $(".fixed_done_manipulators").show();
      return false;
    });
  });
});

// modal
const modal = document.getElementById("myModal");
const closeModal = document.querySelector(".delete-btn");

function openModal() {
  modal.style.display = "flex";
}

window.onclick = function (event) {
  if (event.target == modal) {
    modal.style.display = "none";
  }
};
closeModal.onclick = function () {
  modal.style.display = "none";
};

// api for create product interface on backend
/* document.addEventListener('DOMContentLoaded', () => {
    const saveBtn = document.querySelector('.save-btn');
    const deleteBtn = document.querySelector('.delete-btn');

    saveBtn.addEventListener('click', () => {
        const productId = document.getElementById('product-id').textContent;
        const productName = document.getElementById('product-name').value;
        const price = document.getElementById('price').value;
        const discount = document.getElementById('discount').value;
        const quantity = document.getElementById('quantity').value;
        const managerApproval = document.getElementById('manager-approval').checked;
        const active = document.getElementById('active').checked;
        const description = document.getElementById('description').value;
        const photo = document.getElementById('photo').files[0];

        const formData = new FormData();
        formData.append('productId', productId);
        formData.append('productName', productName);
        formData.append('price', price);
        formData.append('discount', discount);
        formData.append('quantity', quantity);
        formData.append('managerApproval', managerApproval);
        formData.append('active', active);
        formData.append('description', description);
        formData.append('photo', photo);

        fetch('/api/products', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                console.log('Success:', data);
            })
            .catch((error) => {
                console.error('Error:', error);
            });
    });

    deleteBtn.addEventListener('click', () => {
        document.getElementById('product-name').value = '';
        document.getElementById('price').value = '';
        document.getElementById('discount').value = '';
        document.getElementById('quantity').value = '';
        document.getElementById('manager-approval').checked = false;
        document.getElementById('active').checked = false;
        document.getElementById('description').value = '';
        document.getElementById('photo').value = '';

        const editButtons = document.querySelectorAll('.btn.addToCart');
        const editForm = document.querySelector('.container');
        const saveBtn = document.querySelector('.save-btn');
        const deleteBtn = document.querySelector('.delete-btn');

        editButtons.forEach(button => {
            button.addEventListener('click', (event) => {
                const item = event.target.closest('.item');
                const title = item.querySelector('.item_title').textContent;
                const price = item.querySelector('.price').textContent.replace(' &#8381;', '').replace(' ', '');
                const oldPrice = item.querySelector('.old_price').textContent.replace(' &#8381;', '').replace(' ', '');
                const quantity = item.querySelector('.item_stock span').textContent;

                document.getElementById('product-name').value = title;
                document.getElementById('price').value = price;
                document.getElementById('discount').value = ((oldPrice - price) / oldPrice * 100).toFixed(2) + '%';
                document.getElementById('quantity').value = quantity;
                document.getElementById('description').value = title;

                editForm.style.display = 'block';
            });
        });
    });
}); */

document.addEventListener("DOMContentLoaded", () => {
  const addProductButton = document.getElementById("add-product");
  const productsContainer = document.querySelector(".products");

  addProductButton.addEventListener("click", () => {
    const newProduct = document.createElement("div");
    newProduct.classList.add("product");
    newProduct.style.display = "flex";
    newProduct.style.alignItems = "center";
    newProduct.style.marginBottom = "10px";
    newProduct.innerHTML = `
            <img src="https://via.placeholder.com/150" alt="Новый товар" style="margin-right: 20px; border-radius: 8px;">
            <p>Название товара</p>
            <p>Кол-во: <input type="number" value="1" min="1"></p>
            <p>Стоимость: <input type="text" value="0 ₽"></p>
        `;
    productsContainer.insertBefore(newProduct, addProductButton);
  });

  const statusSelect = document.getElementById("status");
  statusSelect.addEventListener("change", () => {
    const status = statusSelect.value;
    console.log("Статус изменен на:", status);
  });

});


document.addEventListener('DOMContentLoaded', () => {
    const addManagerButton = document.getElementById('add-manager-button');
    const addManagerForm = document.getElementById('add-manager-form');
    const saveManagerButton = document.getElementById('save-manager');
    const cancelButton = document.getElementById('cancel');

    addManagerButton.addEventListener('click', () => {
        addManagerForm.style.display = 'flex';
    });

    cancelButton.addEventListener('click', () => {
        addManagerForm.style.display = 'none';
    });

    saveManagerButton.addEventListener('click', () => {
        const name = document.getElementById('name').value;
        const id = document.getElementById('id').value;
        const receiveMessages = document.getElementById('receive-messages').checked;
        const contactFeedback = document.getElementById('contact-feedback').checked;

        if (name && id) {
            const newManager = document.createElement('div');
            newManager.classList.add('manager');
            newManager.style.marginBottom = '20px';
            newManager.innerHTML = `
                <div class="manager-info" style="display: flex;">
                    <div class="avatar" style="width: 50px; height: 50px; background-color: #ddd; border-radius: 50%; margin-right: 20px;"></div>
                    <div class="details">
                        <p>${name}</p>
                        <p>ID: ${id}</p>
                        <p>Получать сообщения: <input type="checkbox" ${receiveMessages ? 'checked' : ''} disabled></p>
                        <p>Контакт для обратной связи: <input type="checkbox" ${contactFeedback ? 'checked' : ''} disabled></p>
                    </div>
                </div>
            `;

            const managersContainer = document.querySelector('.managers');
            managersContainer.insertBefore(newManager, addManagerButton.parentElement);

            // Clear form fields
            document.getElementById('name').value = '';
            document.getElementById('id').value = '';
            document.getElementById('receive-messages').checked = false;
            document.getElementById('contact-feedback').checked = false;

            addManagerForm.style.display = 'none';
        } else {
            alert('Пожалуйста, заполните все поля.');
        }
    });
});