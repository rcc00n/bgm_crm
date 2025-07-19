from django import template
from datetime import datetime
register = template.Library()

@register.filter
def get_by_key(dict_obj, key):
    return dict_obj.get(key)

@register.filter
def string_to_ampm(value):
    try:
        dt = datetime.strptime(value, "%H:%M")  # Или "%H:%M" — зависит от формата
        time_str = dt.strftime("%I:%M %p")  # 12-часовой формат с ведущим нулём
        time_str = time_str.lstrip("0")
        return time_str.lower().replace('am', 'a.m.').replace('pm', 'p.m.')
    except (ValueError, TypeError) as e:
        print(e)
        return value  # вернёт как есть, если формат некорректен