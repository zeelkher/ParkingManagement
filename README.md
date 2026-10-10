# PARKSAFE

**A practical Django parking management system for vehicle tracking, space control, billing, and receipts.**

PARKSAFE helps parking operators manage vehicle check-ins and checkouts across multiple parking areas, floors, and slots. It tracks availability in real time, calculates parking charges automatically, and generates payment-ready receipts with QR code support.

## Features

- **Vehicle check-in** — Record vehicle, owner, contact, vehicle type, plate type, and assigned parking slot.
- **Plate validation** — Supports Indian state-code and BH-series registration validation.
- **Parking layout management** — Organise parking areas into floors and individual slots.
- **Live availability** — See occupied, available, and maintenance-marked spaces at a glance.
- **Automatic billing** — Calculates parking duration and charges during checkout.
- **Digital receipts** — Generates receipts with configurable payment QR code data or an uploaded QR image.
- **Parking history** — Review completed records and protect deletion with staff authentication.
- **Maintenance controls** — Mark a parking area, floor, or slot unavailable while it is under maintenance.

## Built with

- [Python](https://www.python.org/)
- [Django 4.2](https://www.djangoproject.com/)
- SQLite for local development
- Pillow for image and QR-code uploads

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/zeelkher/ParkingManagement.git
cd ParkingManagement
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```bat
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply database migrations

```bash
python manage.py migrate
```

### 5. Create an administrator account *(optional)*

```bash
python manage.py createsuperuser
```

### 6. Start the development server

```bash
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

## Parking rates

| Vehicle type | First hour | Each additional hour |
| --- | ---: | ---: |
| Bike / Motorcycle | ₹20 | ₹10 |
| Car / Jeep / Van | ₹50 | ₹20 |
| Auto-rickshaw | ₹30 | ₹15 |
| Truck / Lorry / Tempo | ₹100 | ₹50 |
| Bus | ₹120 | ₹60 |

## Configuration and deployment

Before deployment, configure the following environment variables. A sample is available in [`.env.example`](.env.example).

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | A long, randomly generated private Django key. |
| `DJANGO_DEBUG` | Set to `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames, for example `example.com,www.example.com`. |

For a local shell session, load values from a `.env` file before running Django:

```bash
set -a
source .env
set +a
python manage.py runserver
```

> Never commit `.env`, `db.sqlite3`, or uploaded media files. They are excluded by the project’s `.gitignore`.

## Project structure

```text
ParkingManagement/
├── parking/                  # Core app: models, views, forms, templates, and static files
├── parking_system/           # Django project settings and URLs
├── media/                    # Local uploaded QR images (not committed)
├── manage.py                 # Django command entry point
├── requirements.txt          # Python dependencies
└── RELEASE_NOTES.md          # Release history
```

## Release

See [RELEASE_NOTES.md](https://github.com/zeelkher/ParkingManagement/blob/main/RELEASE_NOTES.md) for details about the first public release.

## Contributing

Contributions are welcome. Please open an issue to discuss significant changes before submitting a pull request.

## License

Distributed under the [MIT License](LICENSE).
