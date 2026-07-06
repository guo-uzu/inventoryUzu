# Inventory Collector — Supabase Version

## What this is

`inventory_collector_supabase.py` — the program employees run. Two small
popups ask for **full name** and **company email**, then it silently
collects: computer name, logged-in user, OS + version, CPU, RAM, disk
space, serial/service tag, IP, and MAC address, and inserts it all as one
row directly into a Supabase (Postgres) table.

No consolidation step needed anymore — every submission is already in
the database, viewable live in the Supabase Table Editor, DBeaver,
pgAdmin, or any Postgres client.

## 1. Create the table in Supabase

In your Supabase project: **SQL Editor > New query**, paste the contents
of `supabase_setup.sql`, and run it. This creates the `inventory_reports`
table and — importantly — a Row Level Security policy that only allows
**inserting** rows with the public `anon` key, never reading, editing, or
deleting. That matters because the key gets embedded in the `.exe`, and
anyone can extract strings from a compiled executable. With insert-only
RLS, extracting the key only lets someone add fake rows (annoying, but
not a data leak) — never read or tamper with real employee data.

## 2. Get your project's URL and anon key

Supabase dashboard → **Project Settings → API**:

- `Project URL` → goes into `SUPABASE_URL`
- `anon` `public` key → goes into `SUPABASE_ANON_KEY`

Never use the `service_role` key here — that one bypasses RLS entirely
and must stay server-side only.

Edit these two lines near the top of `inventory_collector_supabase.py`:

```python
SUPABASE_URL = "https://YOUR-PROJECT-REF.supabase.co"
SUPABASE_ANON_KEY = "YOUR-ANON-PUBLIC-KEY"
```

## 3. Build the .exe (must be done on a Windows machine)

PyInstaller compiles for whatever OS it runs on, so build it on Windows:

```bash
pip install -r requirements_supabase.txt

pyinstaller --onefile --noconsole --name InventoryCollector inventory_collector_supabase.py
```

The finished file is at `dist/InventoryCollector.exe` — the single file
to hand out to employees.

## 4. Distribute

Send `InventoryCollector.exe` to employees. They double-click it, enter
their name and email, and their machine's data lands in Supabase within
seconds.

## 5. Viewing / using the data

- **Supabase Table Editor**: instant spreadsheet-like view in the browser,
  filterable/sortable, exportable to CSV any time.
- **DBeaver / pgAdmin / any Postgres client**: Supabase dashboard →
  Project Settings → Database → Connection string. Use the "Session
  pooler" or direct connection string with your DB password.
- **Your own server**: same Postgres connection string works from any
  backend, cron job, or BI tool (Metabase, Grafana, etc.).

## Fallback if offline

If a machine can't reach Supabase (VPN issue, no internet, firewall), the
script saves the same data as a local `.json` file in
`~/InventoryBackup/` and tells the employee to notify IT, so nothing is
lost. You can write a tiny script later to re-POST those files if it
ever comes up.

## If you'd rather go through your own backend instead

Supabase's REST API is optional — since the underlying DB is just
Postgres, you can also point `inventory_collector_supabase.py` at your
own internal API endpoint instead of Supabase directly, and have that
endpoint do the DB insert. Useful if you want extra validation, logging,
or to avoid embedding any DB credentials in the `.exe` at all. Happy to
adapt the script that way if you'd prefer it.
