from django.db import migrations


def ensure_master_profiles(apps, schema_editor):
    MasterProfile = apps.get_model("core", "MasterProfile")
    Role = apps.get_model("core", "Role")
    UserRole = apps.get_model("core", "UserRole")
    User = apps.get_model("auth", "User")

    master_role = Role.objects.filter(name="Master").first()
    if not master_role:
        return

    master_user_ids = list(
        UserRole.objects.filter(role=master_role).values_list("user_id", flat=True).distinct()
    )
    if not master_user_ids:
        return

    User.objects.filter(pk__in=master_user_ids, is_staff=False).update(is_staff=True)

    existing_profile_ids = set(
        MasterProfile.objects.filter(user_id__in=master_user_ids).values_list("user_id", flat=True)
    )
    for user_id in master_user_ids:
        if user_id not in existing_profile_ids:
            MasterProfile.objects.create(user_id=user_id)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0121_adminfavoritepage_adminrecentpage_and_more"),
    ]

    operations = [
        migrations.RunPython(ensure_master_profiles, migrations.RunPython.noop),
    ]
