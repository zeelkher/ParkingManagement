# PARKSAFE

A Django-based parking management system for recording vehicle entry and exit, managing parking locations and slots, calculating fees, and producing payment receipts.

## Features

- Vehicle check-in with registration and plate-type validation
- Multi-area, multi-floor, and multi-slot parking layout
- Availability and maintenance tracking for areas, floors, and slots
- Vehicle checkout with automatic duration and parking-fee calculation
- Receipt generation with configurable payment QR codes
- Searchable parking history and staff-authorised record deletion

## Technology

- Python and Django 4.2
- SQLite for local development
- Pillow for QR/image uploads

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Apply database migrations:

   ```bash
   python manage.py migrate
   ```

4. Optionally create an administrator account:

   ```bash
   python manage.py createsuperuser
   ```

5. Start the app:

   ```bash
   python manage.py runserver
   ```

Open `http://127.0.0.1:8000/` in your browser.

## Configuration

Copy `.env.example` to `.env` and set the production values before deployment. In particular, use a private, randomly generated `DJANGO_SECRET_KEY`, set `DJANGO_DEBUG=False`, and define `DJANGO_ALLOWED_HOSTS`.

## Release notes

See [RELEASE_NOTES.md](RELEASE_NOTES.md) for the first public release.

## License

This project is licensed under the [MIT License](LICENSE).
