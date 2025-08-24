from django import forms
from .models import Order
from django import forms
from .models import Category, CarMake, CarModel
from django import forms
from .models import Category, CarMake, CarModel

class ProductFilterForm(forms.Form):
    category = forms.ModelChoiceField(
        label="Category",
        queryset=Category.objects.all(),
        required=False,
        empty_label="All categories",
    )
    make = forms.ModelChoiceField(
        label="Make",
        queryset=CarMake.objects.all().order_by("name"),
        required=False,
        empty_label="Any make",
    )
    model = forms.ModelChoiceField(
        label="Model",
        queryset=CarModel.objects.none(),
        required=False,
        empty_label="Any model",
    )
    year = forms.IntegerField(
        label="Year",
        required=False,
        min_value=1950,
        max_value=2100,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        data = self.data if self.is_bound else self.initial
        make_id = data.get("make")
        if make_id:
            self.fields["model"].queryset = (
                CarModel.objects.filter(make_id=make_id).order_by("name")
            )
        else:
            self.fields["model"].queryset = (
                CarModel.objects.all().order_by("make__name", "name")
            )

            
class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            "customer_name", "email", "phone",
            "vehicle_make", "vehicle_model", "vehicle_year",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
