from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import Appointment
from store.models import Order

from . import services
from . import emails


@receiver(post_save, sender=Appointment)
def appointment_created(sender, instance, created, **kwargs):
    if not created:
        return

    transaction.on_commit(lambda: services.notify_about_appointment(instance.pk))
    transaction.on_commit(lambda: emails.send_appointment_confirmation(instance.pk))


@receiver(post_save, sender=Order)
def order_created(sender, instance, created, **kwargs):
    if not created:
        return

    transaction.on_commit(lambda: services.notify_about_order(instance.pk))
