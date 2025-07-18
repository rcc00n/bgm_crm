from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_datetime
from django.contrib.admin.views.decorators import staff_member_required
from datetime import timedelta
import json

from .models import Appointment

