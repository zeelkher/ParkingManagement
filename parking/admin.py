from django.contrib import admin

from .models import ParkingArea, ParkingFloor, ParkingRecord, ParkingSlot, Vehicle


class ParkingFloorInline(admin.TabularInline):
    model = ParkingFloor
    extra = 1


@admin.register(ParkingArea)
class ParkingAreaAdmin(admin.ModelAdmin):
    list_display = ('name', 'address')
    search_fields = ('name', 'address')
    inlines = (ParkingFloorInline,)


class ParkingSlotInline(admin.TabularInline):
    model = ParkingSlot
    extra = 3


@admin.register(ParkingFloor)
class ParkingFloorAdmin(admin.ModelAdmin):
    list_display = ('name', 'parking_area', 'sort_order')
    list_filter = ('parking_area',)
    inlines = (ParkingSlotInline,)


@admin.register(ParkingSlot)
class ParkingSlotAdmin(admin.ModelAdmin):
    list_display = ('number', 'parking_floor', 'sort_order')
    list_filter = ('parking_floor__parking_area', 'parking_floor')
    search_fields = ('number',)


@admin.register(ParkingRecord)
class ParkingRecordAdmin(admin.ModelAdmin):
    list_display = ('vehicle', 'parking_slot', 'slot_number', 'status', 'entry_time', 'exit_time')
    list_filter = ('status',)
    search_fields = ('vehicle__vehicle_number',)


admin.site.register(Vehicle)
