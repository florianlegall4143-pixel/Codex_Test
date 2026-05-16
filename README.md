# FLE CMMS Asset Database

Stage 1 local-first CMMS-style asset database.

## Start

Double-click:

```text
start_cmms_app.bat
```

Or run manually:

```powershell
C:\Users\FLO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe server.py
```

Then open:

```text
http://localhost:8000
```

Default login:

```text
Email: admin@example.com
Password: admin123
```

Other seeded test logins:

```text
manager@example.com / manager123
technician@example.com / technician123
```

Change the default password after first use.

## What Is Included

- Staff login with Admin, Manager, and Technician roles
- SQLite database stored at `data/cmms.sqlite`
- Asset list, detail, create, edit, archive
- Manual asset IDs with uniqueness validation
- Location management
- Category/status/criticality lookup management
- CSV/XLSX asset import with preview and row errors
- CSV asset export
- Dedicated asset picture shown in the asset list
- Asset manuals and document attachments

## Import Columns

Supported asset import columns:

- `asset_id`
- `name`
- `location`
- `category`
- `status`
- `description`
- `make`
- `model`
- `serial_number`
- `supplier`
- `purchase_date`
- `install_date`
- `warranty_expiry`
- `criticality`
- `notes`
