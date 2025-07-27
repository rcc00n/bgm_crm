from django.db import migrations, models
from storages.backends.s3boto3 import S3Boto3Storage

def copy_urls_to_file(apps, schema_editor):
    ClientFile = apps.get_model('core', 'ClientFile')
    for cf in ClientFile.objects.all():
        # file_url может хранить полный URL; обрежьте домен при необходимости
        path = cf.file_url.lstrip('/')          # пример: 'client_files/abc.jpg'
        if path:
            cf.file.name = path                 # FileField хранит относительный путь
            cf.save(update_fields=['file'])

class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_servicecategory_service_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientfile",
            name="file",
            field=models.FileField(
                upload_to="client_files/",
                storage=S3Boto3Storage(),
                null=True,      # временно разрешаем NULL
                blank=True,
            ),
        ),
        migrations.RunPython(copy_urls_to_file, migrations.RunPython.noop),
        # (необязательно) уберите старое поле, когда убедитесь, что данные перенесены:
        # migrations.RemoveField(model_name="clientfile", name="file_url"),
        # migrations.AlterField(... null=False, blank=False),  # сделать обязательным
    ]
