# Generated by Django 2.2.11 on 2020-03-27 19:14

import django.core.files.storage
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_change_exporter_models'),
    ]

    operations = [
        migrations.AlterField(
            model_name='upload',
            name='file',
            field=models.FileField(max_length=255, storage=django.core.files.storage.FileSystemStorage(location='/var/lib/pulp/upload/'), upload_to=''),
        ),
    ]
