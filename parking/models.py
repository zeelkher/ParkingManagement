from django.db import models
from django.utils import timezone

PLATE_TYPES = [
    ('white_black',       'Private Vehicle'),
    ('yellow_black',      'Commercial Vehicle'),
    ('green_white',       'Electric Vehicle (Private)'),
    ('green_yellow',      'Electric Vehicle (Commercial)'),
    ('black_yellow',      'Self-Drive Rental'),
    ('red_white',         'Temporary Registration'),
    ('dealer_trade',      'Dealer / Trade Plate'),
    ('blue_white',        'Diplomatic / Consular'),
    ('military_black',    'Military (Armed Forces)'),
    ('military_police',   'Military Police'),
    ('red_emblem',        'Constitutional Authorities'),
    ('bh_series',         'BH Series (Bharat)'),
]

VEHICLE_TYPES = [
    ('Car', 'Car'),
    ('Bike', 'Bike'),
    ('Motorcycle', 'Motorcycle'),
    ('Truck', 'Truck'),
    ('Bus', 'Bus'),
    ('Auto-rickshaw', 'Auto-rickshaw'),
    ('Lorry', 'Lorry'),
    ('Tractor', 'Tractor'),
    ('Tempo', 'Tempo'),
    ('Jeep', 'Jeep'),
    ('Van', 'Van'),
    ('Other', 'Other'),
]

class Vehicle(models.Model):
    vehicle_number = models.CharField(max_length=20, unique=True, help_text="e.g. GJ 00 AA 0000 or BH 24 ZA 0001")
    owner_name     = models.CharField(max_length=100)
    mobile         = models.CharField(max_length=15)
    vehicle_type   = models.CharField(max_length=20, choices=VEHICLE_TYPES)
    plate_type     = models.CharField(max_length=20, choices=PLATE_TYPES, default='white_black')
    state_code     = models.CharField(max_length=5, blank=True, help_text="e.g. MH, DL, KA")

    def __str__(self):
        return f"{self.vehicle_number} ({self.owner_name})"

    def get_plate_colors(self):
        """Return (plate_bg_color, text_color, label) for rendering the plate."""
        color_map = {
            'white_black':  ('#FFFFFF', '#000000', 'Private Vehicle'),
            'yellow_black': ('#FFD700', '#000000', 'Commercial Vehicle'),
            'green_white':  ('#008000', '#FFFFFF', 'Electric Vehicle (Private)'),
            'green_yellow': ('#008000', '#FFD700', 'Electric Vehicle (Commercial)'),
            'black_yellow': ('#1a1a1a', '#FFD700', 'Self-Drive Rental'),
            'red_white':    ('#FFD700', '#CC0000', 'Temporary Registration'),
            'dealer_trade': ('#CC0000', '#FFFFFF', 'Dealer / Trade Plate'),
            'blue_white':   ('#003580', '#FFFFFF', 'Diplomatic / Consular'),
            'military_black': ('#1a1a1a', '#FFFFFF', 'Military (Armed Forces)'),
            'military_police': ('#FFFFFF', '#CC0000', 'Military Police'),
            'red_emblem':   ('#CC0000', '#FFD700', 'Constitutional Authorities'),
            # Kept for plates already saved with the previous category.
            'arrow_red':    ('#1a1a1a', '#CC0000', 'Military'),
            'bh_series':    ('#FFFFFF', '#000000', 'BH Series'),
        }
        return color_map.get(self.plate_type, ('#FFFFFF', '#000000', 'Unknown'))


class ParkingArea(models.Model):
    """A physical parking place, for example Main Building or Annex."""
    name = models.CharField(max_length=80, unique=True)
    address = models.CharField(max_length=160, blank=True)
    payment_qr_data = models.CharField(
        max_length=1000,
        blank=True,
        help_text='Payment or verification data encoded in receipt QR codes, for example a UPI payment link.',
    )
    payment_qr_image = models.ImageField(
        upload_to='qr_codes/',
        blank=True,
        null=True,
        help_text='Upload a QR code image to show on receipts.',
    )
    total_slots = models.PositiveIntegerField(default=100, help_text='Maximum number of slots across all floors')
    is_under_maintenance = models.BooleanField(default=False, help_text='If checked, this parking area is under maintenance')

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    @property
    def has_maintenance_items(self):
        """Check if this area or any of its floors/slots are under maintenance."""
        return (self.floors.filter(is_under_maintenance=True).exists() or 
                self.floors.prefetch_related('slots').filter(slots__is_under_maintenance=True).exists())


class ParkingFloor(models.Model):
    parking_area = models.ForeignKey(ParkingArea, on_delete=models.CASCADE, related_name='floors')
    name = models.CharField(max_length=50, help_text='For example: Ground Floor, Floor 1')
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_under_maintenance = models.BooleanField(default=False, help_text='If checked, this floor is under maintenance')

    class Meta:
        ordering = ('parking_area', 'sort_order', 'name')
        constraints = [
            models.UniqueConstraint(fields=('parking_area', 'name'), name='unique_floor_per_area'),
        ]

    def __str__(self):
        return f'{self.parking_area.name} — {self.name}'

    @property
    def slot_prefix(self):
        first_slot = self.slots.order_by('sort_order', 'number').first()
        return first_slot.number.rsplit('-', 1)[0] if first_slot else ''

    @property
    def has_slots_under_maintenance(self):
        """Check if any slots in this floor are under maintenance."""
        return self.slots.filter(is_under_maintenance=True).exists()


class ParkingSlot(models.Model):
    parking_floor = models.ForeignKey(ParkingFloor, on_delete=models.CASCADE, related_name='slots')
    number = models.CharField(max_length=20, help_text='For example: G-01, A-12, VIP-3')
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_under_maintenance = models.BooleanField(default=False, help_text='If checked, this slot is not available for parking')

    class Meta:
        ordering = ('parking_floor', 'sort_order', 'number')
        constraints = [
            models.UniqueConstraint(fields=('parking_floor', 'number'), name='unique_slot_per_floor'),
        ]

    @property
    def label(self):
        return f'{self.parking_floor.parking_area.name} • {self.parking_floor.name} • {self.number}'

    def __str__(self):
        return self.label


class ParkingRecord(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Exited', 'Exited'),
    ]

    vehicle     = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    parking_slot = models.ForeignKey(
        ParkingSlot, on_delete=models.PROTECT, related_name='records'
    )
    slot_number = models.IntegerField()
    # A default (rather than auto_now_add) permits authorised back-dated entries.
    entry_time  = models.DateTimeField(default=timezone.now)
    exit_time   = models.DateTimeField(null=True, blank=True)
    total_hours = models.FloatField(null=True, blank=True)
    parking_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Active')

    def __str__(self):
        return f"{self.vehicle.vehicle_number} - Slot {self.slot_number} - {self.status}"

    @property
    def floor_name(self):
        """Return the name of the configured floor for this parking record."""
        return self.parking_slot.parking_floor.name

    @property
    def floor_slot_number(self):
        """Position of the configured slot on its floor."""
        return self.parking_slot.sort_order

    @property
    def parking_number(self):
        return self.parking_slot.number

    @property
    def parking_area_name(self):
        return self.parking_slot.parking_floor.parking_area.name

    # Property to get user-friendly duration string
    @property
    def formatted_duration(self):
        # Return dash if total hours is not calculated yet (active vehicle)
        if not self.total_hours:
            return "—"
        # Convert total float hours to rounded minutes
        total_minutes = int(round(self.total_hours * 60))
        # 1440 minutes in a day (24 hours * 60 minutes)
        days = total_minutes // 1440
        # Calculate remaining minutes after days are subtracted
        remaining_minutes = total_minutes % 1440
        # Calculate hours from remaining minutes
        hours = remaining_minutes // 60
        # Calculate remaining minutes
        mins = remaining_minutes % 60
        
        # Build the formatted string output parts list
        parts = []
        if days > 0:
            parts.append(f"{days}d") # E.g., '1d'
        if hours > 0 or days > 0:
            parts.append(f"{hours}h") # E.g., '5h'
        if mins > 0 or (days == 0 and hours == 0):
            parts.append(f"{mins}m") # E.g., '30m'
            
        # Join components with space (e.g. '1d 5h 30m')
        return " ".join(parts)


class BookingFormConfig(models.Model):
    """Configuration for the public advance booking form set up by operator."""
    title = models.CharField(max_length=150, default="Advance Parking Reservation")
    description = models.TextField(
        blank=True,
        default="Reserve your parking slot in advance. Our team will review your request and confirm slot allocation."
    )
    is_published = models.BooleanField(
        default=True,
        help_text="When enabled, public customers can view and submit advance bookings."
    )

    # Standard field visibility & requirement toggles
    field_owner_name_visible = models.BooleanField(default=True)
    field_owner_name_required = models.BooleanField(default=True)

    field_mobile_visible = models.BooleanField(default=True)
    field_mobile_required = models.BooleanField(default=True)

    field_vehicle_number_visible = models.BooleanField(default=True)
    field_vehicle_number_required = models.BooleanField(default=True)

    field_vehicle_type_visible = models.BooleanField(default=True)
    field_vehicle_type_required = models.BooleanField(default=True)

    field_expected_arrival_visible = models.BooleanField(default=True)
    field_expected_arrival_required = models.BooleanField(default=True)

    field_duration_hours_visible = models.BooleanField(default=True)
    field_duration_hours_required = models.BooleanField(default=False)

    field_state_code_visible = models.BooleanField(default=True)
    field_state_code_required = models.BooleanField(default=False)

    field_plate_type_visible = models.BooleanField(default=True)
    field_plate_type_required = models.BooleanField(default=False)

    field_preferred_area_visible = models.BooleanField(default=True)
    field_preferred_area_required = models.BooleanField(default=False)

    field_notes_visible = models.BooleanField(default=True)
    field_notes_required = models.BooleanField(default=False)

    # Advance booking parameters
    advance_booking_lead_hours = models.PositiveIntegerField(
        default=1,
        help_text="Minimum notice required before arrival (in hours)"
    )
    max_advance_days = models.PositiveIntegerField(
        default=7,
        help_text="Maximum days in advance customers can request a booking"
    )
    terms_and_conditions = models.TextField(
        blank=True,
        default="1. Please arrive within 30 minutes of your scheduled arrival time.\n2. Carry or display your Booking Reference upon arrival.\n3. Standard parking tariffs apply starting from check-in time."
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(id=1)
        return config

    def __str__(self):
        return f"Booking Form Config ({'Published' if self.is_published else 'Draft'})"


class BookingCustomQuestion(models.Model):
    QUESTION_TYPES = [
        ('text', 'Short Text'),
        ('textarea', 'Long Text / Note'),
        ('select', 'Dropdown Select'),
        ('checkbox', 'Checkbox (Yes / No)'),
        ('number', 'Number'),
    ]

    form_config = models.ForeignKey(BookingFormConfig, on_delete=models.CASCADE, related_name='custom_questions')
    question_text = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='text')
    options = models.TextField(blank=True, help_text="Comma-separated options for dropdown selection")
    help_text = models.CharField(max_length=255, blank=True)
    is_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('sort_order', 'id')

    def __str__(self):
        return self.question_text

    def get_options_list(self):
        if not self.options:
            return []
        return [opt.strip() for opt in self.options.split(',') if opt.strip()]


class AdvanceBooking(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Awaiting Operator Confirmation'),
        ('Confirmed', 'Confirmed'),
        ('Rejected', 'Rejected'),
        ('Cancelled', 'Cancelled'),
        ('Checked In', 'Checked In'),
        ('Expired', 'Expired'),
    ]

    booking_reference = models.CharField(max_length=24, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending', db_index=True)

    # Customer & Vehicle Details
    owner_name = models.CharField(max_length=100, blank=True)
    mobile = models.CharField(max_length=15)
    vehicle_number = models.CharField(max_length=20)
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPES, default='Car')
    plate_type = models.CharField(max_length=20, choices=PLATE_TYPES, default='white_black')
    state_code = models.CharField(max_length=5, blank=True)
    preferred_area = models.ForeignKey(ParkingArea, on_delete=models.SET_NULL, null=True, blank=True, related_name='advance_requests')
    notes = models.TextField(blank=True)

    # Schedule
    expected_arrival_time = models.DateTimeField()
    expected_duration_hours = models.FloatField(default=2.0, null=True, blank=True)

    # Dynamic answers for custom questions {question_id: answer_text}
    custom_answers = models.JSONField(default=dict, blank=True)

    # Operator Allocation
    assigned_slot = models.ForeignKey(ParkingSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name='advance_bookings')
    confirmed_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_bookings')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    operator_notes = models.TextField(blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)

    # Check-in linkage
    parking_record = models.OneToOneField(ParkingRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='advance_booking')
    checked_in_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.booking_reference} - {self.vehicle_number} ({self.status})"

    @classmethod
    def generate_reference(cls):
        import random
        while True:
            ref = f"BK-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
            if not cls.objects.filter(booking_reference=ref).exists():
                return ref

    def get_plate_colors(self):
        color_map = {
            'white_black':  ('#FFFFFF', '#000000', 'Private Vehicle'),
            'yellow_black': ('#FFD700', '#000000', 'Commercial Vehicle'),
            'green_white':  ('#008000', '#FFFFFF', 'Electric Vehicle (Private)'),
            'green_yellow': ('#008000', '#FFD700', 'Electric Vehicle (Commercial)'),
            'black_yellow': ('#1a1a1a', '#FFD700', 'Self-Drive Rental'),
            'red_white':    ('#FFD700', '#CC0000', 'Temporary Registration'),
            'dealer_trade': ('#CC0000', '#FFFFFF', 'Dealer / Trade Plate'),
            'blue_white':   ('#003580', '#FFFFFF', 'Diplomatic / Consular'),
            'military_black': ('#1a1a1a', '#FFFFFF', 'Military (Armed Forces)'),
            'military_police': ('#FFFFFF', '#CC0000', 'Military Police'),
            'red_emblem':   ('#CC0000', '#FFD700', 'Constitutional Authorities'),
            'bh_series':    ('#FFFFFF', '#000000', 'BH Series'),
        }
        return color_map.get(self.plate_type, ('#FFFFFF', '#000000', 'Unknown'))

