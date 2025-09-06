document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".send-notify-btn").forEach(button => {
        button.addEventListener("click", () => {
            const userId = button.dataset.userId;
            const userName = button.dataset.userName;
            const message = prompt(`Enter the message for ${userName}:`);
            if (!message) return;

            fetch('/admin/send_notification/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                body: JSON.stringify({
                    user_id: userId,
                    message: message,
                }),
            })
                .then(res => res.json())
                .then(data => {
                    if (data.status === "ok") {
                        alert("Message sent!");
                    } else {
                        alert("Error while sending");
                    }
                });
        });
    });
});

function getCSRFToken() {
    const name = 'csrftoken';
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        if (cookie.trim().startsWith(name + '=')) {
            return decodeURIComponent(cookie.trim().substring(name.length + 1));
        }
    }
    return null;
}