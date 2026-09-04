import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "clubbot.db"


async def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await init(db)
    return db


async def init(db: aiosqlite.Connection):
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS panels (
            name TEXT PRIMARY KEY,
            channel_id INTEGER,
            message_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS attendance (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'offen',
            reason TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS roster (
            user_id INTEGER PRIMARY KEY,
            area TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            by_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sanctions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            reason TEXT NOT NULL,
            until_text TEXT,
            by_id INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inventory (
            item TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'Sonstiges',
            qty INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS inventory_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            delta INTEGER NOT NULL,
            who_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS equipment (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'ungeprüft',
            missing TEXT
        );

        CREATE TABLE IF NOT EXISTS workers (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            phone TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS vacations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'beantragt',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS infos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS equipment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS activity (
            user_id INTEGER PRIMARY KEY,
            stamped_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            by_id INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lootdrops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS einkauf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS routechecks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clip_channels (
            user_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS activity_fails (
            user_id INTEGER PRIMARY KEY,
            fails INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS abgaben (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    await db.commit()

    seeded = await get_setting(db, "rules_seed", "0")
    if seeded != "2":
        await db.execute("DELETE FROM catalog")
        from rules_data import SANCTION_RULES
        await db.executemany(
            "INSERT INTO catalog (name, description) VALUES (?, ?)",
            [(f"REGEL {n} {title}", folge) for n, title, folge in SANCTION_RULES],
        )
        await set_setting(db, "rules_seed", "2")

    # Lager einmalig mit den Gegenständen vom Bild befüllen
    lager_seed = await get_setting(db, "lager_seed_v2", "0")
    if lager_seed != "1":
        seed_items = [
            # Essen
            ("Crunchy Chicken Burger", "Essen", 165),
            ("Tiramisu", "Essen", 50),
            ("Rinderfilet Steak", "Essen", 95),
            ("Rumpsteak", "Essen", 90),
            ("Pecan Pie Cake", "Essen", 50),
            ("Rib Eye Steak", "Essen", 100),
            ("Caesar Salat", "Essen", 80),
            ("Pancakes", "Essen", 45),
            ("Lachs", "Essen", 9),
            ("Bachforelle", "Essen", 8),
            # Trinken
            ("Ayran Kirsch", "Trinken", 24),
            ("Mineralwasser", "Trinken", 36),
            ("Bubble Tea", "Trinken", 10),
            ("Energy Drink", "Trinken", 24),
            # Sonstiges
            ("OG Kush Joint", "Sonstiges", 2),
            ("GPS", "Sonstiges", 13),
            ("Klebeband", "Sonstiges", 2),
            ("Kupfererz", "Sonstiges", 51),
            ("Sack", "Sonstiges", 5),
            ("Schrott", "Sonstiges", 11),
            ("Schere", "Sonstiges", 4),
        ]
        for name, kat, qty in seed_items:
            await db.execute(
                "INSERT INTO inventory(item, category, qty) VALUES(?, ?, ?) "
                "ON CONFLICT(item) DO UPDATE SET category=excluded.category, qty=excluded.qty",
                (name, kat, qty),
            )
        await set_setting(db, "lager_seed_v2", "1")
        await set_setting(db, "lager_cleared", "1")

    cur = await db.execute("SELECT COUNT(*) AS c FROM equipment_items")
    if (await cur.fetchone())["c"] == 0:
        await db.executemany(
            "INSERT INTO equipment_items (name) VALUES (?)",
            [("Diensthandy",), ("Funk",), ("Uniform",), ("Ausweis geprüft",)],
        )

    cur = await db.execute("SELECT COUNT(*) AS c FROM infos")
    if (await cur.fetchone())["c"] == 0:
        await db.execute(
            "INSERT INTO infos (title, body, updated_at) VALUES (?, ?, datetime('now','localtime'))",
            (
                "Willkommen",
                "Hier stehen Infos, die auf der Website eingetragen werden. Leitung kann Texte anlegen, ändern und löschen. Der Discord-Bot übernimmt sie in die Info-Liste.",
            ),
        )
    try:
        await db.execute("ALTER TABLE routes ADD COLUMN amount TEXT DEFAULT ''")
    except Exception:
        pass
    await db.commit()


async def get_setting(db, key, default=None):
    cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else default


async def set_setting(db, key, value):
    await db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    await db.commit()


async def get_panel(db, name):
    cur = await db.execute("SELECT * FROM panels WHERE name = ?", (name,))
    return await cur.fetchone()


async def set_panel(db, name, channel_id, message_id):
    await db.execute(
        """
        INSERT INTO panels(name, channel_id, message_id) VALUES(?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET channel_id = excluded.channel_id, message_id = excluded.message_id
        """,
        (name, channel_id, message_id),
    )
    await db.commit()
