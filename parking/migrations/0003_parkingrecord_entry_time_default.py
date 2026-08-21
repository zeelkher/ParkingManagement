# Generated manually for date/time entry support.
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('parking', '0002_vehicle_plate_type_vehicle_state_code_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='parkingrecord',
            name='entry_time',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
