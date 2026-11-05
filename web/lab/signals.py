from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def record_session_epoch(sender, request, user, **kwargs):
    request.session["lab_epoch"] = user.session_epoch
