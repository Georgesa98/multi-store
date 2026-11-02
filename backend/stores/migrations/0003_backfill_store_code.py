from django.db import migrations, models
from django.utils.text import slugify


def backfill_codes(apps, schema_editor):
    Store = apps.get_model("stores", "Store")
    used = set()
    for store in Store.objects.order_by("created_at"):
        base = "".join(ch for ch in slugify(store.name).upper() if ch.isalnum())[:8]
        base = base or "STORE"
        candidate = base
        i = 2
        while candidate in used:
            suffix = str(i)
            candidate = f"{base[: 8 - len(suffix)]}{suffix}"
            i += 1
        used.add(candidate)
        Store.objects.filter(pk=store.pk).update(code=candidate)


class Migration(migrations.Migration):
    dependencies = [("stores", "0002_store_code")]

    operations = [
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="store",
            name="code",
            field=models.CharField(max_length=8, unique=True),
        ),
    ]
