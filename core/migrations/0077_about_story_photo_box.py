from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0076_update_typography_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo",
            field=models.ImageField(blank=True, help_text="Optional photo shown in the Our Story section.", null=True, upload_to="about/story/"),
        ),
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo_alt",
            field=models.CharField(default="Denim & Kacy at Bad Guy Motors", max_length=160),
        ),
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo_placeholder",
            field=models.CharField(default="DK", help_text="Fallback initials shown when no photo is uploaded.", max_length=12),
        ),
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo_title",
            field=models.CharField(default="Denim & Kacy", max_length=80),
        ),
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo_subtitle",
            field=models.CharField(default="Co-owners, Bad Guy Motors", max_length=120),
        ),
        migrations.AddField(
            model_name="aboutpagecopy",
            name="story_photo_caption",
            field=models.CharField(default="Built on grit, family, and second chances.", max_length=200),
        ),
    ]
