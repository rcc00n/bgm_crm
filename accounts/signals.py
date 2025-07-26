# from django.contrib.auth.signals import user_logged_in
# from django.dispatch import receiver

# @receiver(user_logged_in)
# def mark_recent_admin_login(sender, request, user, **kwargs):
#     """
#     Ставим флаг только если логинились через форму админ-панели.
#     """
#     if request.path.startswith("/admin/login"):
#         request.session["recent_admin_login"] = True
