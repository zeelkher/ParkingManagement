import re
from django import forms
from django.utils import timezone
from .models import (
    ParkingArea, ParkingFloor, Vehicle, ParkingSlot, PLATE_TYPES, VEHICLE_TYPES,
    BookingFormConfig, BookingCustomQuestion, AdvanceBooking
)

DURATION_CHOICES = [
    (1.0, '1 Hour'),
    (2.0, '2 Hours'),
    (3.0, '3 Hours'),
    (4.0, '4 Hours'),
    (5.0, '5 Hours'),
    (6.0, '6 Hours'),
    (7.0, '7 Hours'),
    (8.0, '8 Hours'),
    (9.0, '9 Hours'),
    (10.0, '10 Hours'),
    (11.0, '11 Hours'),
    (12.0, '12 Hours (Half Day)'),
    (13.0, '13 Hours'),
    (14.0, '14 Hours'),
    (15.0, '15 Hours'),
    (16.0, '16 Hours'),
    (17.0, '17 Hours'),
    (18.0, '18 Hours'),
    (19.0, '19 Hours'),
    (20.0, '20 Hours'),
    (21.0, '21 Hours'),
    (22.0, '22 Hours'),
    (23.0, '23 Hours'),
    (24.0, '24 Hours (1 Day)'),
]


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
        """Normalize to standard spaced format e.g. 'GJ 05 AA 1234' / '24 BH 1234 AA'."""
        raw = self.cleaned_data['vehicle_number'].strip().upper()
        # Collapse any accidental double-spaces, keep single spaces between groups
        return ' '.join(raw.split())

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


class BookingFormSettingsForm(forms.ModelForm):
    class Meta:
        model = BookingFormConfig
        fields = [
            'title', 'description', 'is_published',
            'field_owner_name_visible', 'field_owner_name_required',
            'field_mobile_visible', 'field_mobile_required',
            'field_vehicle_number_visible', 'field_vehicle_number_required',
            'field_vehicle_type_visible', 'field_vehicle_type_required',
            'field_expected_arrival_visible', 'field_expected_arrival_required',
            'field_duration_hours_visible', 'field_duration_hours_required',
            'field_state_code_visible', 'field_state_code_required',
            'field_plate_type_visible', 'field_plate_type_required',
            'field_preferred_area_visible', 'field_preferred_area_required',
            'field_notes_visible', 'field_notes_required',
            'advance_booking_lead_hours', 'max_advance_days',
            'terms_and_conditions'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Advance Parking Reservation'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Instructions for visitors'}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'form_is_published'}),
            'advance_booking_lead_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'max_advance_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'terms_and_conditions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }


class BookingCustomQuestionForm(forms.ModelForm):
    class Meta:
        model = BookingCustomQuestion
        fields = ['question_text', 'field_type', 'options', 'help_text', 'is_required', 'sort_order']
        widgets = {
            'question_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Company or Department Name'}),
            'field_type': forms.Select(attrs={'class': 'form-control'}),
            'options': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Option 1, Option 2, Option 3 (for Dropdown)'}),
            'help_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Helpful hint for visitor'}),
            'is_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }


class PublicAdvanceBookingForm(forms.Form):
    def __init__(self, *args, config=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config or BookingFormConfig.get_solo()

        # Add standard fields conditionally based on config
        if self.config.field_vehicle_number_visible:
            self.fields['vehicle_number'] = forms.CharField(
                label='Vehicle Number',
                required=self.config.field_vehicle_number_required,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'GJ 01 AA 1234',
                    'id': 'id_vehicle_number',
                    'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:2px;font-size:16px;font-weight:700;',
                })
            )

        if self.config.field_state_code_visible:
            self.fields['state_code'] = forms.CharField(
                label='State Code',
                max_length=5,
                required=self.config.field_state_code_required,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'GJ',
                    'id': 'id_state_code',
                    'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:3px;font-size:17px;font-weight:800;',
                })
            )
            self.fields['bh_series'] = forms.BooleanField(
                label='BH Series',
                required=False,
                widget=forms.CheckboxInput(attrs={
                    'class': 'form-check-input',
                    'id': 'id_bh_series',
                })
            )

        if self.config.field_owner_name_visible:
            self.fields['owner_name'] = forms.CharField(
                label='Your Name / Driver Name',
                max_length=100,
                required=self.config.field_owner_name_required,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'FULL NAME',
                    'style': 'text-transform:uppercase;',
                })
            )

        if self.config.field_mobile_visible:
            self.fields['mobile'] = forms.CharField(
                label='Mobile Number',
                max_length=10,
                required=self.config.field_mobile_required,
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': '9876543210',
                    'maxlength': '10',
                    'inputmode': 'numeric',
                    'id': 'id_mobile',
                })
            )

        if self.config.field_vehicle_type_visible:
            self.fields['vehicle_type'] = forms.ChoiceField(
                label='Vehicle Type',
                choices=VEHICLE_TYPES,
                initial='Car',
                required=self.config.field_vehicle_type_required,
                widget=forms.Select(attrs={'class': 'form-control'})
            )

        if self.config.field_plate_type_visible:
            self.fields['plate_type'] = forms.ChoiceField(
                label='Number Plate Category',
                choices=PLATE_TYPES,
                initial='white_black',
                required=self.config.field_plate_type_required,
                widget=forms.Select(attrs={'class': 'form-control'})
            )

        if self.config.field_expected_arrival_visible:
            self.fields['expected_arrival_time'] = forms.DateTimeField(
                label='Expected Arrival Date & Time',
                required=self.config.field_expected_arrival_required,
                input_formats=['%Y-%m-%dT%H:%M', '%d-%m-%Y %H:%M'],
                widget=forms.DateTimeInput(
                    format='%Y-%m-%dT%H:%M',
                    attrs={'class': 'form-control', 'type': 'datetime-local'}
                ),
                help_text=f'Bookings can be made {self.config.advance_booking_lead_hours} hr+ in advance (up to {self.config.max_advance_days} days).'
            )

        if self.config.field_duration_hours_visible:
            self.fields['expected_duration_hours'] = forms.TypedChoiceField(
                label='Estimated Parking Duration',
                choices=DURATION_CHOICES,
                initial=2.0,
                coerce=float,
                required=self.config.field_duration_hours_required,
                widget=forms.Select(attrs={
                    'class': 'form-control',
                    'id': 'id_expected_duration_hours',
                }),
                help_text='Select expected stay duration (1 to 24 hours).'
            )

        if self.config.field_preferred_area_visible:
            self.fields['preferred_area'] = forms.ModelChoiceField(
                queryset=ParkingArea.objects.filter(is_under_maintenance=False),
                label='Preferred Parking Area',
                empty_label='Any Available Area',
                required=self.config.field_preferred_area_required,
                widget=forms.Select(attrs={'class': 'form-control'})
            )

        if self.config.field_notes_visible:
            self.fields['notes'] = forms.CharField(
                label='Special Requests / Notes',
                required=self.config.field_notes_required,
                widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'e.g., Near elevator, EV charging point preference, etc.'})
            )

        # Dynamic Custom Questions
        for q in self.config.custom_questions.filter(is_active=True):
            field_name = f'custom_question_{q.id}'
            if q.field_type == 'textarea':
                self.fields[field_name] = forms.CharField(
                    label=q.question_text,
                    help_text=q.help_text,
                    required=q.is_required,
                    widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
                )
            elif q.field_type == 'select':
                options = [(opt, opt) for opt in q.get_options_list()]
                self.fields[field_name] = forms.ChoiceField(
                    label=q.question_text,
                    help_text=q.help_text,
                    choices=[('', 'Select an option')] + options,
                    required=q.is_required,
                    widget=forms.Select(attrs={'class': 'form-control'})
                )
            elif q.field_type == 'checkbox':
                self.fields[field_name] = forms.BooleanField(
                    label=q.question_text,
                    help_text=q.help_text,
                    required=q.is_required,
                    widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
                )
            elif q.field_type == 'number':
                self.fields[field_name] = forms.IntegerField(
                    label=q.question_text,
                    help_text=q.help_text,
                    required=q.is_required,
                    widget=forms.NumberInput(attrs={'class': 'form-control'})
                )
            else:
                self.fields[field_name] = forms.CharField(
                    label=q.question_text,
                    help_text=q.help_text,
                    required=q.is_required,
                    widget=forms.TextInput(attrs={'class': 'form-control'})
                )

    def clean_mobile(self):
        mobile = self.cleaned_data.get('mobile', '').strip()
        if mobile:
            clean = ''.join(filter(str.isdigit, mobile))
            if len(clean) != 10:
                raise forms.ValidationError('Mobile number must be exactly 10 digits.')
            if clean[0] not in '6789':
                raise forms.ValidationError('Mobile number must start with 6, 7, 8, or 9.')
            return clean
        return mobile

    def clean_vehicle_number(self):
        vnum = self.cleaned_data.get('vehicle_number', '').strip().upper()
        if not vnum:
            return vnum

        clean = re.sub(r'[^A-Z0-9]', '', vnum)

        # 1. BH Series: YY BH NNNN LL (e.g. 24 BH 1234 AA or 22 BH 9999 A)
        bh_m = re.match(r'^([0-9]{2})(BH)([0-9]{4})([A-Z]{1,2})$', clean)
        if bh_m:
            return f"{bh_m.group(1)} {bh_m.group(2)} {bh_m.group(3)} {bh_m.group(4)}"

        # 2. Standard Indian vehicle number: SS DD LL NNNN (e.g. GJ 01 AA 1234, MH 12 1234, DL 01 C 1234)
        std_m = re.match(r'^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{1,4})$', clean)
        if std_m:
            s, r, ser, n = std_m.groups()
            if len(r) == 1:
                r = f"0{r}"
            n = n.zfill(4)
            parts = [s, r]
            if ser:
                parts.append(ser)
            parts.append(n)
            return ' '.join(parts)

        # 3. DL special / vintage series: DL 3C AB 1234
        dl_m = re.match(r'^([A-Z]{2})([0-9][A-Z])([A-Z]{0,2})([0-9]{1,4})$', clean)
        if dl_m:
            s, r, ser, n = dl_m.groups()
            parts = [s, r]
            if ser:
                parts.append(ser)
            parts.append(n.zfill(4))
            return ' '.join(parts)

        raise forms.ValidationError(
            'Please enter a valid vehicle registration number in proper format (e.g. GJ 01 AA 1234 or 24 BH 1234 AA).'
        )

    def clean_expected_arrival_time(self):
        arr_time = self.cleaned_data.get('expected_arrival_time')
        if arr_time:
            now = timezone.now()
            max_delta = timezone.timedelta(days=self.config.max_advance_days)
            # Allow 5 minute grace margin
            if arr_time < (now - timezone.timedelta(minutes=5)):
                raise forms.ValidationError('Arrival time cannot be in the past.')
            if arr_time > (now + max_delta):
                raise forms.ValidationError(f'Bookings can be requested at most {self.config.max_advance_days} days in advance.')
        return arr_time


class BookingStatusCheckForm(forms.Form):
    booking_reference = forms.CharField(
        label='Booking Reference',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. BK-4920-8172',
            'style': 'text-transform:uppercase;font-family:"JetBrains Mono",monospace;letter-spacing:2px;font-size:16px;font-weight:700;',
        })
    )
    mobile = forms.CharField(
        label='Registered Mobile Number',
        max_length=10,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '9876543210',
            'maxlength': '10',
            'inputmode': 'numeric',
        })
    )
