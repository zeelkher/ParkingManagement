from django.db import migrations


def create_default_layout(apps, schema_editor):
    ParkingArea = apps.get_model('parking', 'ParkingArea')
    ParkingFloor = apps.get_model('parking', 'ParkingFloor')
    ParkingSlot = apps.get_model('parking', 'ParkingSlot')
    ParkingRecord = apps.get_model('parking', 'ParkingRecord')

    area, _ = ParkingArea.objects.get_or_create(name='Main Parking')
    floor_specs = [('Ground Floor', 'G'), ('Floor 1', 'F1'), ('Floor 2', 'F2'), ('Floor 3', 'F3')]
    slot_by_legacy_number = {}
    for floor_index, (floor_name, prefix) in enumerate(floor_specs):
        floor, _ = ParkingFloor.objects.get_or_create(
            parking_area=area, name=floor_name, defaults={'sort_order': floor_index}
        )
        for position in range(1, 26):
            slot, _ = ParkingSlot.objects.get_or_create(
                parking_floor=floor,
                number=f'{prefix}-{position:02d}',
                defaults={'sort_order': position},
            )
            slot_by_legacy_number[floor_index * 25 + position] = slot.id

    for record in ParkingRecord.objects.filter(parking_slot__isnull=True):
        slot_id = slot_by_legacy_number.get(record.slot_number)
        if slot_id:
            record.parking_slot_id = slot_id
            record.save(update_fields=('parking_slot',))


def remove_default_layout(apps, schema_editor):
    ParkingArea = apps.get_model('parking', 'ParkingArea')
    ParkingArea.objects.filter(name='Main Parking').delete()


class Migration(migrations.Migration):
    dependencies = [('parking', '0005_parkingarea_parkingfloor_parkingslot_and_more')]

    operations = [migrations.RunPython(create_default_layout, remove_default_layout)]
