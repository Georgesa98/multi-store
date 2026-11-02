from django.db import migrations, models


class Migration(migrations.Migration):
    """Add `Store.code` nullable first so existing rows can be backfilled."""

    dependencies = [("stores", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="store",
            name="code",
            field=models.CharField(
                blank=True, max_length=8, null=True, unique=True
            ),
        ),
    ]
