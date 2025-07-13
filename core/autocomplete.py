from dal import autocomplete
from .models import ServiceMaster

class ServiceMasterAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return ServiceMaster.objects.none()

        qs = ServiceMaster.objects.select_related('master', 'service')

        if self.q:
            qs = qs.filter(service__name__icontains=self.q)

        return qs