# Generated by Django 3.0.5 on 2020-04-10 18:51

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('secretgraph', '0001_initial'),
    ]

    operations = []

    if (
        getattr(settings, "AUTH_USER_MODEL", None) or
        getattr(settings, "SECRETGRAPH_BIND_TO_USER", False)
    ):
        dependencies.append(
            migrations.swappable_dependency(settings.AUTH_USER_MODEL)
        )
        operations.append(migrations.AddField(
            model_name='cluster',
            name='user',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, related_name="clusters"
            ),
        ))
