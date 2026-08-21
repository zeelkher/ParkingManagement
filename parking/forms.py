from django import forms
from django.utils import timezone
from .models import ParkingArea, ParkingFloor, Vehicle, ParkingSlot, PLATE_TYPES, VEHICLE_TYPES


class ParkingFloorChoiceField(forms.ModelChoiceField):
    """Display a floor's own name after its parking area has been selected."""

    def label_from_instance(self, floor):
        return floor.name


class ParkingSlotChoiceField(forms.ModelChoiceField):
    """Display only the slot identifier after its floor has been selected."""

    def label_from_instance(self, slot):
        return slot.number


class VehicleEntryForm(forms.Form):
    vehicle_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'GJ 00 AA 0000',
            'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:2px;font-size:16px;',
            'id': 'id_vehicle_number',
        })
    )
    owner_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'FULL NAME',
            'style': 'text-transform:uppercase;',
        })
    )
    mobile = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '9876543210',
            'maxlength': '10',
            'inputmode': 'numeric',
            'id': 'id_mobile',
        })
    )
    vehicle_type = forms.ChoiceField(
        choices=VEHICLE_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    plate_type = forms.ChoiceField(
        choices=PLATE_TYPES,
        initial='white_black',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    state_code = forms.CharField(
        max_length=5,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'MH',
            'maxlength': '5',
            'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:3px;font-size:18px;font-weight:700;',
            'id': 'id_state_code',
        })
    )
    bh_series = forms.BooleanField(
        label='BH Series Vehicle',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input',
            'id': 'id_bh_series',
        })
    )
    parking_area = forms.ModelChoiceField(
        queryset=ParkingArea.objects.filter(is_under_maintenance=False),
        label='Parking Area',
        empty_label='Select Parking Area',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    parking_floor = ParkingFloorChoiceField(
        queryset=ParkingFloor.objects.filter(is_under_maintenance=False).none(),
        label='Parking Floor',
        empty_label='Select Parking Floor',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    parking_slot = ParkingSlotChoiceField(
        queryset=ParkingSlot.objects.none(),
        label='Available Parking Slot',
        empty_label='Select Available Slot',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Only currently available slots are listed. Select where this vehicle will park.'
    )
    entry_time = forms.DateTimeField(
        label='Entry date & time',
        input_formats=['%Y-%m-%dT%H:%M', '%d-%m-%Y %H:%M'],
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'class': 'form-control', 'type': 'datetime-local', 'readonly': True}
        ),
        help_text='Set automatically when the vehicle is checked in.',
    )

    def __init__(self, *args, available_slots=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['entry_time'].initial = timezone.localtime().replace(second=0, microsecond=0)
        if available_slots is not None:
            self.fields['parking_slot'].queryset = available_slots
            self.fields['parking_floor'].queryset = ParkingFloor.objects.select_related('parking_area').filter(
                is_under_maintenance=False, parking_area__is_under_maintenance=False
            )
            self.fields['parking_area'].queryset = ParkingArea.objects.filter(is_under_maintenance=False)

    def clean_entry_time(self):
        """Always record the check-in time on the server, not a user-supplied value."""
        return timezone.now()

    def clean_vehicle_number(self):
        return self.cleaned_data['vehicle_number'].strip().upper()

    def clean_state_code(self):
        return self.cleaned_data['state_code'].strip().upper()

    def clean_owner_name(self):
        return self.cleaned_data['owner_name'].strip().upper()

    def clean_mobile(self):
        mobile = self.cleaned_data['mobile'].strip()
        if mobile.startswith('+91'):
            mobile = mobile[3:].strip()
        elif mobile.startswith('91') and len(mobile) == 12:
            mobile = mobile[2:].strip()
        mobile = mobile.replace(' ', '').replace('-', '')
        if not mobile.isdigit():
            raise forms.ValidationError('Mobile number must contain only digits.')
        if len(mobile) != 10:
            raise forms.ValidationError('Mobile number must be exactly 10 digits (without +91 prefix).')
        if mobile[0] not in '6789':
            raise forms.ValidationError('Mobile number must start with 6, 7, 8, or 9.')
        return mobile

    def clean(self):
        cleaned = super().clean()
        vnum  = cleaned.get('vehicle_number', '').upper()
        state = cleaned.get('state_code', '').upper()
        bh_series = cleaned.get('bh_series', False)
        area = cleaned.get('parking_area')
        floor = cleaned.get('parking_floor')
        slot = cleaned.get('parking_slot')
        
        # Check BH Series format
        if bh_series:
            # BH registration is national, so it always uses BH instead of a state code.
            cleaned['state_code'] = 'BH'
            if not vnum.startswith('BH'):
                raise forms.ValidationError(
                    'BH Series is selected, but vehicle number must start with "BH" (e.g., BH 01 AA 0001).'
                )
        
        # Check state code validation (skip for BH Series as BH is not a state code)
        if vnum and state and len(vnum) >= 2 and len(state) >= 2 and not bh_series:
            if vnum[:2] != state[:2]:
                raise forms.ValidationError(
                    f"Vehicle number prefix '{vnum[:2]}' does not match "
                    f"state code '{state[:2]}'. Both must start with the same letters (e.g. MH)."
                )
        
        if floor and area and floor.parking_area_id != area.id:
            self.add_error('parking_floor', 'Select a floor that belongs to the selected parking area.')
        if slot and floor and slot.parking_floor_id != floor.id:
            self.add_error('parking_slot', 'Select an available slot on the selected floor.')
        return cleaned


class VehicleExitForm(forms.Form):
    vehicle_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'GJ 00 AA 0000',
            'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:2px;font-size:18px;font-weight:600;',
            'id': 'id_exit_vehicle_number',
        })
    )
    exit_time = forms.DateTimeField(
        label='Exit date & time',
        input_formats=['%Y-%m-%dT%H:%M', '%d-%m-%Y %H:%M'],
        widget=forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={'class': 'form-control', 'type': 'datetime-local', 'readonly': True}
        ),
        help_text='Set automatically when the vehicle is checked out.'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['exit_time'].initial = timezone.localtime().replace(second=0, microsecond=0)

    def clean_vehicle_number(self):
        return self.cleaned_data['vehicle_number'].strip().upper()

    def clean_exit_time(self):
        """Always use the server checkout time rather than a submitted value."""
        return timezone.now()


class ParkingAreaForm(forms.ModelForm):
    class Meta:
        model = ParkingArea
        fields = ('name', 'address', 'payment_qr_data', 'payment_qr_image', 'total_slots', 'is_under_maintenance')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Main Parking'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional location details'}),
            'payment_qr_data': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. upi://pay?pa=merchant@bank'}),
            'payment_qr_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'total_slots': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'e.g. 100'}),
            'is_under_maintenance': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_total_slots(self):
        total_slots = self.cleaned_data['total_slots']
        used_slots = (
            sum(floor.slots.count() for floor in self.instance.floors.all())
            if self.instance.pk else 0
        )
        if total_slots < used_slots:
            raise forms.ValidationError(
                f'Total slots cannot be lower than the {used_slots} slots already created.'
            )
        return total_slots


class ParkingFloorForm(forms.ModelForm):
    slot_prefix = forms.CharField(
        max_length=12,
        label='Slot identifier',
        help_text='The part before the dash, for example G, F1, or B.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. G'})
    )
    slot_count = forms.IntegerField(
        min_value=1,
        label='Number of slots on this floor',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'e.g. 30'})
    )
    parking_area = forms.ModelChoiceField(
        queryset=ParkingArea.objects.filter(is_under_maintenance=False),
        empty_label='Select Parking Area',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = ParkingFloor
        fields = ('parking_area', 'name', 'sort_order', 'is_under_maintenance')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Floor 1'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_under_maintenance': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            first_slot = self.instance.slots.order_by('sort_order', 'number').first()
            if first_slot:
                self.fields['slot_prefix'].initial = first_slot.number.rsplit('-', 1)[0]
            self.fields['slot_count'].initial = self.instance.slots.count()

    def clean_slot_prefix(self):
        return self.cleaned_data['slot_prefix'].strip().upper().replace(' ', '')

    def clean(self):
        cleaned = super().clean()
        area = cleaned.get('parking_area')
        slot_count = cleaned.get('slot_count')
        if area and slot_count:
            other_slots = ParkingSlot.objects.filter(parking_floor__parking_area=area)
            if self.instance.pk:
                other_slots = other_slots.exclude(parking_floor=self.instance)
            if other_slots.count() + slot_count > area.total_slots:
                self.add_error(
                    'slot_count',
                    f'This would exceed the parking area capacity of {area.total_slots} slots.'
                )
        return cleaned

class ParkingSlotForm(forms.ModelForm):
    class Meta:
        model = ParkingSlot
        fields = ('parking_floor', 'number', 'sort_order', 'is_under_maintenance')
        widgets = {
            'parking_floor': forms.Select(attrs={'class': 'form-control'}),
            'number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. F1-01'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_under_maintenance': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parking_floor'].empty_label = 'Select Parking Floor'
