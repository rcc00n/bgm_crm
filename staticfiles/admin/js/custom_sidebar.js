document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.getElementById("sidebar");

    sidebar.addEventListener("mouseleave", () => {
        // Закрываем все открытые дропдауны, когда мышь уходит с сайдбара
        const openDropdowns = sidebar.querySelectorAll(".dropdown.open");
        openDropdowns.forEach(dropdown => dropdown.classList.remove("open"));
    });
});

function toggleDropdown(clickedElement) {
    const allDropdowns = document.querySelectorAll(".icon-sidebar .dropdown");

    allDropdowns.forEach(dropdown => {
        if (dropdown !== clickedElement.parentElement) {
            dropdown.classList.remove("open");
        }
    });

    clickedElement.parentElement.classList.toggle("open");
}