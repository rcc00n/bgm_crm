function getLocalDateString(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function changeDateToToday() {
    const today = getLocalDateString();
    document.getElementById('realDateInput').value = today;
    onDateChange(today);
}

function changeDateByDays(days) {
    const input = document.getElementById('realDateInput');

    // Преобразуем вручную в YYYY-MM-DD → локальная дата
    const [year, month, day] = input.value.split('-').map(Number);
    const currentDate = new Date(year, month - 1, day); // ← важно: месяц от 0
    currentDate.setHours(12);  // 👈 Устанавливаем безопасное время (чтобы избежать смещений при DST)

    // Меняем дату
    currentDate.setDate(currentDate.getDate() + days);

    const newDate = getLocalDateString(currentDate);
    input.value = newDate;

    onDateChange(newDate);
}

function onDateChange(value) {
    const display = document.getElementById("displayDate");
    display.textContent = value;

    const formData = new FormData(document.getElementById("filterForm"));
    formData.append("action", "calendar");
    formData.set("date", value);  // заменяем дату

    const params = new URLSearchParams(formData).toString();

    fetch(`/admin/core/appointment/?${params}`, {
        headers: { 'x-requested-with': 'XMLHttpRequest' }
    })
        .then(res => res.json())
        .then(data => {
            document.getElementById("calendar-container").innerHTML = data.html;
            attachTooltipHandlers();
            syncCalendarScrollHeight();
        });
}


const sidebar = document.getElementById("filterSidebar");
const filterBtn = document.getElementById("nav-icon2");
const filterForm = document.getElementById("filterForm");

filterBtn.addEventListener("click", () => {

    sidebar.classList.remove("hidden");
    setTimeout(() => sidebar.classList.add("visible"), 200);
});
function closeSidebar() {
    sidebar.classList.remove("visible");
    setTimeout(() => sidebar.classList.add("hidden"), 350);
}

function toggleSection(el) {
    const content = el.nextElementSibling;
    content.style.display = content.style.display === 'block' ? 'none' : 'block';
}

function clearAllFilters() {
    // Сброс чекбоксов
    document.querySelectorAll('#filterForm input[type="checkbox"]').forEach(cb => cb.checked = false);
    // Сброс селектов
    document.querySelectorAll('#filterForm select').forEach(sel => sel.value = "");
}

// Преобразуем несколько чекбоксов в один параметр запроса: ?status=1&status=2
filterForm.addEventListener("submit", function (e) {
    e.preventDefault();

    const formData = new FormData(filterForm);
    formData.append("action", "filter");
    const selectedDate = document.getElementById("realDateInput").value;
    formData.append("date", selectedDate);
    const params = new URLSearchParams(formData).toString();

    fetch(`?${params}`, {
        headers: {
            "X-Requested-With": "XMLHttpRequest"
        }
    })
        .then(res => res.json())
        .then(data => {
            document.getElementById("calendar-container").innerHTML = data.html;
            attachTooltipHandlers();
            syncCalendarScrollHeight();
            closeSidebar();
        })
        .catch(err => {
            console.error("Error loading appointments:", err);
        });
});
function syncCalendarScrollHeight() {
    const scrollable = document.querySelector(".scrollable");
    if (!scrollable) {
        return;
    }
    const rect = scrollable.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const bottomPadding = 12;
    const available = viewportHeight - rect.top - bottomPadding;
    const height = Math.max(240, Math.floor(available));
    scrollable.style.height = `${height}px`;
    scrollable.style.maxHeight = `${height}px`;
}
let popup = document.getElementById("addPopup");
let popupTime = document.getElementById("popupTime");


let lastActiveCell = null;

function showAddPopup(event, time, label) {
    closePopup();

    const cell = event.currentTarget;
    cell.innerHTML = `<span class="cell-label">${label}</span>`;
    const rect = cell.getBoundingClientRect();
    const masterId = cell.dataset.master;
    cell.value = time;
    // Обновить текст времени
    const popupTimeEl = document.getElementById("popupTime");
    popupTimeEl.textContent = label;

    lastActiveCell = cell;
    cell.classList.add("active");

    // Заполняем тело popup-а новыми действиями
    const popupBody = popup.querySelector(".popup-body");
    popupBody.innerHTML = `
        <div class="popup-action" onclick="handleAdd('appointment', '${time}', '${masterId}')">📅 Add appointment</div>
        <div class="popup-action" onclick="handleAdd('vacation', '${time}', '${masterId}')">🗓️ Add time off</div>
    `;

    if ((rect.left + window.scrollX - 230) < 0 || rect.width < 100) {
        // либо слишком близко к левому краю, либо слишком узкая ячейка
        popup.style.left = `${rect.left + window.scrollX + rect.width + 10}px`;
    } else {
        popup.style.left = `${rect.left + window.scrollX - rect.width/2.5}px`;
    }
    popup.style.top = `${rect.top + window.scrollY - 40}px`;


    popup.classList.remove("hidden");
}

function closePopup() {
    popup.classList.add("hidden");

    // Сбросить активную ячейку
    if (lastActiveCell) {
        lastActiveCell.classList.remove("active");
        lastActiveCell.innerHTML = ``;
        lastActiveCell = null;
    }
}

document.addEventListener("click", function (e) {
    if (!popup.contains(e.target) && !e.target.classList.contains("calendar-cell")) {
        closePopup();
    }
});

const tooltip = document.getElementById("apptTooltip");

function attachTooltipHandlers() {
    document.querySelectorAll(".event").forEach(box => {
        box.addEventListener("mouseenter", function () {
            showTooltip(box);
        });
        box.addEventListener("mouseleave", function () {
            hideTooltip();
        });
    });
    document.querySelectorAll(".unavailable-cell").forEach(cell => {
        cell.addEventListener("click", () => {
            const id = cell.dataset.id;
            if (id) {
                window.location.href = `/admin/core/masteravailability/${id}/change/`;
            }
        });
    });
    document.querySelectorAll(".unavailable-cell").forEach(cell => {
        cell.addEventListener("mouseenter", () => showUnavailableTooltip(cell));
        cell.addEventListener("mouseleave", () => hideTooltip());
    });
}

attachTooltipHandlers();
syncCalendarScrollHeight();

window.addEventListener("resize", syncCalendarScrollHeight);

function showTooltip(box) {
    const rect = box.getBoundingClientRect();
    const client = box.dataset.client || "";
    const phone = box.dataset.phone || "";
    const service = box.dataset.service || "";
    const time = box.dataset.timeLabel || "";
    const status = box.dataset.status || "";
    const duration = box.dataset.duration || "";
    const price = box.dataset.price || "";
    const price_discounted = box.dataset.pricedisc || "";
    const discount = box.dataset.discount || "";
    const master = box.dataset.master || "";

    const firstLetter = client.trim().charAt(0).toUpperCase();
    if (price === price_discounted) {
        let floatNumber = parseFloat(price.replace(/[^0-9.]/g, '')); // 150.00
        let intNumber = Math.round(floatNumber); // 150
        let final_price = 0;
        if(discount === ""){
            final_price = intNumber;
        }
        else {
            final_price = intNumber * (1 - parseInt(discount)/(-1*100));
        }

        tooltip.innerHTML = `
        <div class="tooltip-card">
            <div class="tooltip-header">
                <span>${time}</span>
                <span>${status}</span>
            </div>
            <div class="tooltip-body">
                <div class="tooltip-client">
                    <div class="tooltip-avatar">${firstLetter}</div>
                    <div class="tooltip-client-info">
                        <div class="tooltip-client-name">${client}</div>
                        <div class="tooltip-client-phone">${phone}</div>
                    </div>
                </div>

                <div class="tooltip-footer">
                    <div class="tooltip-service">${service}</div>
                    <div class="tooltip-price">$${final_price}</div>
                </div>
                <div class="tooltip-meta">${master} · ${duration}</div>
            </div>
        </div>
    `;
    }
    else {
        let floatNumber = parseFloat(price_discounted.replace(/[^0-9.]/g, ''));
        let intNumber = Math.round(floatNumber);

        tooltip.innerHTML = `
        <div class="tooltip-card">
            <div class="tooltip-header">
                <span>${time}</span>
                <span>${status}</span>
            </div>
            <div class="tooltip-body">
                <div class="tooltip-client">
                    <div class="tooltip-avatar">${firstLetter}</div>
                    <div class="tooltip-client-info">
                        <div class="tooltip-client-name">${client}</div>
                        <div class="tooltip-client-phone">${phone}</div>
                    </div>
                </div>

                <div class="tooltip-footer">
                    <div class="tooltip-service">${service}</div>
                    <div>
                    <div class="tooltip-price" style="opacity: 0.5; text-decoration: line-through;">${price}</div>
                    <div class="tooltip-price">$${intNumber * (1 - discount/(-1*100))}</div>
                    </div>
                </div>
                <div class="tooltip-meta">${master} · ${duration}</div>
            </div>
        </div>
    `;
    }
    const card = tooltip.querySelector('.tooltip-card');
    const tooltipWidth = card ? card.offsetWidth : Math.min(320, document.documentElement.clientWidth * 0.8);
    const tooltipHeight = card ? card.offsetHeight : 200;
    const scrollX = window.scrollX || document.documentElement.scrollLeft || 0;
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight;

    let top = rect.top + scrollY + rect.height / 2 - tooltipHeight / 2;
    let left = rect.left + scrollX - tooltipWidth - 12;

    if (left < scrollX + 12) {
        left = rect.right + scrollX + 12;
    }
    if (left + tooltipWidth > scrollX + viewportWidth - 12) {
        left = scrollX + viewportWidth - tooltipWidth - 12;
    }

    const minTop = scrollY + 12;
    const maxTop = scrollY + viewportHeight - tooltipHeight - 12;
    top = Math.min(Math.max(top, minTop), maxTop);
    left = Math.max(left, scrollX + 12);

    tooltip.style.top = `${top}px`;
    tooltip.style.left = `${left}px`;
    tooltip.classList.remove("hidden");
    tooltip.classList.add("visible");
}

function hideTooltip() {
    tooltip.classList.remove("visible");
    tooltip.classList.add("hidden");
}

document.querySelectorAll(".unavailable-cell").forEach(cell => {
    cell.addEventListener("mouseenter", () => showUnavailableTooltip(cell));
    cell.addEventListener("mouseleave", () => hideTooltip());
});

function showUnavailableTooltip(cell) {
    const rect = cell.getBoundingClientRect();
    const reason = cell.dataset.reason || "Unavailable";
    const start = cell.dataset.start || "";
    const end = cell.dataset.end || "";
    const until = cell.dataset.until || "";

    const tooltip = document.getElementById("apptTooltip");

    tooltip.innerHTML = `
        <div class="tooltip-card">
            <div class="tooltip-header">
                <span><strong>${reason.charAt(0).toUpperCase() + reason.slice(1)}</strong></span>
            </div>
            <div class="tooltip-body">
                <div style="font-size:1.6vh; font-weight:500; margin-bottom: 0.66vh;">
                    ${start} - ${end}
                </div>
                ${until ? `<div style="font-size:1.4vh; color:#777;">Ends ${until}</div>` : ""}
            </div>
        </div>
    `;
    const card = tooltip.querySelector('.tooltip-card');
    const tooltipWidth = card ? card.offsetWidth : Math.min(320, document.documentElement.clientWidth * 0.8);
    const tooltipHeight = card ? card.offsetHeight : 150;
    const scrollX = window.scrollX || document.documentElement.scrollLeft || 0;
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight;
    const middleY = rect.top + rect.height / 2 + scrollY;

    let leftX = rect.left + scrollX - tooltipWidth - 12;
    let rightX = rect.right + scrollX + 12;
    let left = leftX;
    if (leftX < scrollX + 12) {
        left = rightX;
    }
    if (left + tooltipWidth > scrollX + viewportWidth - 12) {
        left = scrollX + viewportWidth - tooltipWidth - 12;
    }

    let top = middleY - tooltipHeight / 2;
    const minTop = scrollY + 12;
    const maxTop = scrollY + viewportHeight - tooltipHeight - 12;
    top = Math.min(Math.max(top, minTop), maxTop);

    tooltip.style.top = `${top}px`;
    tooltip.style.left = `${left}px`;
    tooltip.classList.remove("hidden");
    tooltip.classList.add("visible");
}

const addBtn = document.getElementById("addDropdownBtn");
const menu = document.getElementById("addDropdownMenu");
const arrow = document.getElementById("arrow");

addBtn.addEventListener("click", () => {
    menu.classList.toggle("hidden");
    arrow.textContent = menu.classList.contains("hidden") ? "▾" : "▴";
});

// Закрытие по клику вне меню
document.addEventListener("click", (e) => {
    if (!addBtn.contains(e.target) && !menu.contains(e.target)) {
        menu.classList.add("hidden");
        arrow.textContent = "▾";
    }
});

function handleAdd(type) {
    const selectedDate = document.getElementById("realDateInput").value;
    const masterId = lastActiveCell?.dataset?.master;
    const time = lastActiveCell?.value;

    let url = "#";

    if (type === "appointment") {
        url = `/admin/core/appointment/add/?date=${selectedDate}&time=${time}&master=${masterId}`;
    } else if (type === "vacation") {
        url = `/admin/core/masteravailability/add/?date=${selectedDate}&time=${time}&master=${masterId}`;
    } else {
        alert(`"${type}" action is not implemented yet.`);
        return;
    }

    window.location.href = url;
}
