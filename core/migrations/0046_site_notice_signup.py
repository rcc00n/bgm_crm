from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0045_sync_paid_orders_to_payments"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteNoticeSignup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("welcome_code", models.CharField(max_length=40)),
                ("welcome_sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("followup_2_sent_at", models.DateTimeField(blank=True, null=True)),
                ("followup_3_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Site notice signup",
                "verbose_name_plural": "Site notice signups",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="sitenoticesignup",
            index=models.Index(fields=["welcome_sent_at"], name="core_sit_not_welc_81d49c_idx"),
        ),
        migrations.AddIndex(
            model_name="sitenoticesignup",
            index=models.Index(fields=["followup_2_sent_at"], name="core_sit_not_foll_2_5c8c0b_idx"),
        ),
        migrations.AddIndex(
            model_name="sitenoticesignup",
            index=models.Index(fields=["followup_3_sent_at"], name="core_sit_not_foll_3_eb6a87_idx"),
        ),
    ]
