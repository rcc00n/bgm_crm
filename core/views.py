from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Prefetch, Q

from core.models import Appointment, ServiceCategory, Service

@login_required
def client_dashboard(request):
    user = request.user

    # Личные данные/записи клиента (старый функционал сохранён)
    profile = getattr(user, "userprofile", None)
    appointments = (
        Appointment.objects
        .filter(client=user)
        .select_related("service", "master")
        .order_by("-start_time")
    )

    # Каталог
    q = (request.GET.get("q") or "").strip()
    cat = request.GET.get("cat") or ""

    services_qs = Service.objects.select_related("category").order_by("name")
    if q:
        services_qs = services_qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if cat:
        services_qs = services_qs.filter(category__id=cat)

    categories_qs = (
        ServiceCategory.objects.order_by("name")
        .prefetch_related(Prefetch("service_set", queryset=services_qs))
    )

    context = {
        "profile": profile,
        "appointments": appointments,
        "categories": categories_qs,                          # блоки каталога
        "filter_categories": ServiceCategory.objects.order_by("name"),  # селект
        "q": q,
        "active_category": str(cat),
        "search_results": services_qs if q else None,
        "has_any_services": services_qs.exists(),
        "uncategorized": services_qs.filter(category__isnull=True),
    }
    return render(request, "client/mainmenu.html", context)
