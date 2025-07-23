document.addEventListener("DOMContentLoaded", function () {
    const toggleBtn = document.getElementById("sidebar-toggle");
    const sidebar = document.querySelector(".custom-sidebar");

    toggleBtn.addEventListener("click", () => {
        sidebar.classList.toggle("closed");
    });
});

function toggleDropdown(el) {
    el.classList.toggle("open");
}
