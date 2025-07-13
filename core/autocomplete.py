from dal import autocomplete
from .models import Service

class ServiceAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Service.objects.none()

        qs = Service.objects.all()

        if self.q:
            qs = qs.filter(name__icontains=self.q)

        return qs