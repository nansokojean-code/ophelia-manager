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

        CREATE TABLE IF NOT EXISTS web_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            must_change_password INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES web_users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS web_builder_panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_key TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            title_override TEXT NOT NULL DEFAULT '',
            description_override TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'bot',
            color_hex TEXT NOT NULL DEFAULT '#5865F2',
            footer_text TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS web_panel_buttons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_key TEXT NOT NULL,
            button_key TEXT NOT NULL,
            label TEXT NOT NULL,
            style TEXT NOT NULL DEFAULT 'secondary',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(panel_key, button_key)
        );

        CREATE TABLE IF NOT EXISTS web_button_roles (
            panel_key TEXT NOT NULL,
            button_key TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            PRIMARY KEY(panel_key, button_key, role_id)
        );

        CREATE TABLE IF NOT EXISTS web_module_settings (
            panel_key TEXT PRIMARY KEY,
            module_enabled INTEGER NOT NULL DEFAULT 1,
            image_enabled INTEGER NOT NULL DEFAULT 1
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
    # V4 Universal Studio migrations: keep old databases compatible.
    cols = {r[1] for r in await (await db.execute("PRAGMA table_info(web_builder_panels)")).fetchall()}
    migrations = {
        "message_type": "TEXT NOT NULL DEFAULT 'embed'",
        "content_text": "TEXT NOT NULL DEFAULT ''",
        "image_path": "TEXT NOT NULL DEFAULT ''",
        "thumbnail_path": "TEXT NOT NULL DEFAULT ''",
        "image_url": "TEXT NOT NULL DEFAULT ''",
        "thumbnail_url": "TEXT NOT NULL DEFAULT ''",
        "layout": "TEXT NOT NULL DEFAULT 'embed'",
        "auto_send": "INTEGER NOT NULL DEFAULT 0",
        "schedule_time": "TEXT NOT NULL DEFAULT ''",
        "schedule_days": "TEXT NOT NULL DEFAULT ''",
        "schedule_channel_id": "INTEGER",
    }
    for name, ddl in migrations.items():
        if name not in cols:
            await db.execute(f"ALTER TABLE web_builder_panels ADD COLUMN {name} {ddl}")
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS web_setup_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_key TEXT NOT NULL,
            name TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            inline INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS web_setup_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_key TEXT NOT NULL,
            label TEXT NOT NULL,
            style TEXT NOT NULL DEFAULT 'secondary',
            action_type TEXT NOT NULL DEFAULT 'none',
            action_value TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    # Web onboarding migration (safe for existing databases)
    try:
        await db.execute("ALTER TABLE web_users ADD COLUMN onboarding_seen INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    await db.commit()

    button_seed = [
        ("aufstellung", "anmelden", "Anmelden", "success", 1, 10),
        ("aufstellung", "abmelden", "Abmelden", "danger", 1, 20),
        ("aufstellung", "refresh", "Aktualisieren", "secondary", 1, 30),
        ("aufstellung", "shift", "Verschieben", "primary", 1, 40),
    ]
    # V6.2.2: optionales Gewicht fuer Lagerbestand
    cols = await (await db.execute("PRAGMA table_info(inventory)")).fetchall()
    if not any(row[1] == "weight_kg" for row in cols):
        await db.execute("ALTER TABLE inventory ADD COLUMN weight_kg REAL")

    await db.executemany(
        "INSERT INTO web_panel_buttons(panel_key,button_key,label,style,enabled,sort_order) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(panel_key,button_key) DO NOTHING",
        button_seed,
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

    # V6.2.2: Boss-Lager und normales Lager mit festgelegtem Startbestand
    lager_seed = await get_setting(db, "lager_seed_v3", "0")
    if lager_seed != "1":
        boss_items = [
            ("Metall", 17274, 8637.0), ("Holzbox", 92, 92.0),
            ("Schutzweste", 87, 174.0), ("Schwere Weste", 10, 50.0),
            ("Waffenrahmen", 24, 7.2), ("Pistolen-Magazin", 25, 25.0),
            ("SMG-Magazin", 40, 40.0), ("Schrotflinten-Magazin", 20, 20.0),
            ("Semtex", 5, 10.0), ("Kokain", 450, 450.0),
            ("Static Sift", 1, 1.0), ("Frozen Sift", 3, 3.0),
            ("Alien OG", 6, 6.0), ("Purple Skunk", 6, 6.0),
            ("Banana Spliff Cookie", 2, 1.0), ("Amnesia Haze Joint", 3, 1.5),
            ("OG Kush Joint", 1, 0.5), ("Messer", 1, 2.0),
            ("Baseballschläger", 1, 2.0), ("Feuerzeug", 1, 0.2),
            ("Redwood Zigarette", 3, 0.0), ("Flex", 1, 3.0),
        ]
        normal_items = [
            ("Hotdog",70), ("Energy Drink",15), ("Caesar Salat",31),
            ("Pecan Pie Cake",50), ("Rinderfilet Steak",52), ("Rumpsteak",41),
            ("Crunchy Chicken Burger",5), ("Tiramisu",270), ("Erdbeerkuchen",200),
            ("Rib Eye Steak",80), ("Whisky",72), ("Bier",20),
            ("Sprayentferner",28), ("Klammerpflaster",1), ("Sex on the Beach",81),
            ("Handschellen",4), ("Notfallwiederbelebungsset",1), ("Cola",80),
            ("Klebeband",2), ("Bachforelle",8), ("Kupfererz",51), ("Sack",5),
            ("Schrott",11), ("Lachs",9), ("Eistee",40), ("Brot",71),
            ("Mojito",83), ("Teddybear",5), ("Kondom",6), ("Rose",4),
            ("Blumenstrauss",5), ("Softeis – Schokolade",20),
        ]
        # Gewuenschter Bestand ersetzt den bisherigen Lager-Seed vollstaendig.
        await db.execute("DELETE FROM inventory")
        await db.executemany(
            "INSERT INTO inventory(item, category, qty, weight_kg) VALUES(?, 'Boss Lager', ?, ?)",
            boss_items,
        )
        await db.executemany(
            "INSERT INTO inventory(item, category, qty, weight_kg) VALUES(?, 'Normales Lager', ?, NULL)",
            normal_items,
        )
        await set_setting(db, "lager_seed_v3", "1")
        await set_setting(db, "lager_cleared", "1")
        await db.commit()

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

    # Vorhandene Discord-Panels automatisch in den Web-Builder übernehmen.
    legacy_panels = [
        ("mitarbeiter", "Mitarbeiter"),
        ("memberliste", "Memberliste"),
        ("rang", "Rangsystem"),
        ("aufstellung", "Aufstellung"),
        ("dienst", "Dienst / Abmeldung"),
        ("katalog", "Sanktionskatalog"),
        ("sanktionen", "Sanktionen"),
        ("ausruestung", "Ausrüstung / Mitglieder"),
        ("lager", "Lager"),
        ("urlaub", "Urlaub"),
        ("infos", "Information"),
        ("arbeiter", "Arbeiter"),
        ("tickets", "Tickets"),
        ("regeln", "Regeln"),
        ("status", "Clubstatus"),
        ("aktivitaet", "Aktivitätscheck"),
        ("notizen", "Notizen"),
        ("blacklist", "Blacklist"),
        ("pflicht", "Pflicht-Ausrüstungen"),
        ("routen", "Unsere Route"),
        ("einkauf", "Eingekauft"),
        ("routecheck", "Routenkontrolle"),
        ("lootdrop", "Lootdrop abgeben"),
        ("rollenanfrage", "Rollenanfrage"),
        ("rollenbestaetigen", "Rollen bestätigen"),
        ("clipantrag", "Kill-Clip beantragen"),
        ("abgaben", "Abgaben"),
        ("kasse", "Frakkasse"),
    ]
    for order, (panel_key, label) in enumerate(legacy_panels, start=1):
        await db.execute(
            "INSERT INTO web_builder_panels(panel_key,label,source,sort_order) VALUES(?,?, 'bot', ?) "
            "ON CONFLICT(panel_key) DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order WHERE web_builder_panels.source='bot'",
            (panel_key, label, order),
        )
        await db.execute(
            "INSERT INTO web_module_settings(panel_key,module_enabled,image_enabled) VALUES(?,1,1) "
            "ON CONFLICT(panel_key) DO NOTHING",
            (panel_key,),
        )
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
