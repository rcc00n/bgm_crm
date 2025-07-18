from django import template
register = template.Library()

@register.filter
def get_by_key(dict_obj, key):
    return dict_obj.get(key)