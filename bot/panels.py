from collections import defaultdict
from datetime import datetime

import discord

from ranks import ROSTER_AREAS, display_line, hidden_from_lists, highest_rank, rank_names


def now_footer(extra=""):
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M Uhr")
    text = f"Automatische Aktualisierung • {stamp}"
    if extra:
        text = f"Automatische Aktualisierung • {extra} • {stamp}"
    return text


def visible_members(guild):
    people = []
    for m in guild.members:
        if m.bot:
            continue
        if hidden_from_lists(m):
            continue
        people.append(m)
    return people


def staff_members(guild):
    return [m for m in visible_members(guild) if highest_rank(m)]


def ping_ophelia(guild):
    for r in guild.roles:
        if r.name.lower() in {"ophelia", "ophelia familie", "@ophelia"}:
            return r.mention
    return "@Ophelia"


async def embed_mitarbeiter(guild):
    names = rank_names(guild)
    grouped = {r: [] for r in names}
    for m in staff_members(guild):
        rank = highest_rank(m)
        if rank:
            grouped[rank].append(m)

    e = discord.Embed(title="Mitarbeiterliste", color=0x2B2D31)
    lines = []
    if not names:
        e.description = "Noch keine Rang-Rollen gesetzt.\nLeitung: `/rangrollen` mit euren echten Rollen."
        e.set_footer(text=now_footer())
        return e
    for rank in names:
        members = sorted(grouped[rank], key=lambda x: (x.display_name.lower()))
        lines.append(f"**{rank} ({len(members)})**")
        if members:
            lines.extend(display_line(m) for m in members)
        else:
            lines.append("_niemand_")
        lines.append("")
    e.description = "\n".join(lines).strip()
    e.set_footer(text=now_footer("Discord-Rollen + Dienststatus"))
    return e


async def embed_memberliste(guild):
    e = await embed_rangsystem_users(guild)
    e.title = "Memberliste"
    return e


async def embed_rangsystem(guild):
    from rules_data import RANK_INFO
    e = discord.Embed(title="Rangsystem", color=0x3B82C4)
    parts = []
    for name, desc in RANK_INFO:
        parts.append(f"**{name}**")
        parts.append(desc)
        parts.append("")
    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer())
    return e


async def embed_rangsystem_users(guild):
    names = rank_names(guild)
    grouped = {r: [] for r in names}
    for m in staff_members(guild):
        rank = highest_rank(m)
        if rank:
            grouped[rank].append(m)

    e = discord.Embed(title="Memberliste", color=0x2B2D31)
    if not names:
        e.description = "Noch keine Rang-Rollen gesetzt. `/rangrollen` benutzen."
        e.set_footer(text=now_footer())
        return e
    parts = []
    for i, rank in enumerate(names):
        hint = ""
        people = sorted(grouped[rank], key=lambda x: x.display_name.lower())
        parts.append(f"**{rank} ({len(people)}) {hint}**")
        if people:
            parts.extend(display_line(m) for m in people)
        parts.append("")
    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer("Ränge ändert nur die Leitung"))
    return e


async def embed_aufstellung(guild, db):
    import database as dbmod
    zeit = await dbmod.get_setting(db, f"aufstellung_time:{guild.id}", "18:00")
    title = await dbmod.get_setting(db, f"aufstellung_title:{guild.id}", "Aufstellung")
    intro = await dbmod.get_setting(db, f"aufstellung_description:{guild.id}", "Seid pünktlich da.")
    ping_name = await dbmod.get_setting(db, f"aufstellung_ping:{guild.id}", "Ophelia")
    footer = await dbmod.get_setting(db, f"aufstellung_footer:{guild.id}", "Automatische Aktualisierung · Buttons unten")
    color_raw = await dbmod.get_setting(db, f"aufstellung_color:{guild.id}", "#2B2D31")
    layout = await dbmod.get_setting(db, f"aufstellung_layout:{guild.id}", "embed")
    try:
        color = int((color_raw or "#2B2D31").lstrip("#"), 16)
    except ValueError:
        color = 0x2B2D31
    cur = await db.execute("SELECT user_id, status, reason FROM attendance")
    rows = {r["user_id"]: r for r in await cur.fetchall()}
    buckets = {"angemeldet": [], "abgemeldet": [], "offen": []}
    for m in staff_members(guild):
        row = rows.get(m.id); st = row["status"] if row else "offen"
        if st not in buckets: st = "offen"
        buckets[st].append((m, row["reason"] if row else None))
    role = discord.utils.get(guild.roles, name=ping_name) if ping_name else None
    ping_text = role.mention if role else (ping_ophelia(guild) if ping_name else "")
    e = discord.Embed(title=title or "Aufstellung", color=color)
    head = f"**Heute um {zeit} Uhr Aufstellung.**\n{intro}".strip()
    labels = [("Angemeldet","angemeldet"),("Abgemeldet","abgemeldet"),("Offen","offen")]
    if layout == "table":
        lines = [head, "", ping_text, "", "```", "STATUS       RANG  NAME"]
        for label,key in labels:
            for m, reason in sorted(buckets[key], key=lambda x:x[0].display_name.lower()):
                rank = highest_rank(m) or "-"
                lines.append(f"{label[:11]:11} {rank[:5]:5} {m.display_name[:24]}")
        lines.append("```")
        e.description = "\n".join(lines)[:4000]
    elif layout == "compact":
        parts=[head, "", ping_text]
        for label,key in labels:
            names = [display_line(m) for m,_ in sorted(buckets[key], key=lambda x:x[0].display_name.lower())]
            parts += ["", f"**{label} ({len(names)})**", " · ".join(names) if names else "_niemand_"]
        e.description="\n".join(parts)[:4000]
    else:
        parts=[head, "", ping_text]
        for label,key in labels:
            items=sorted(buckets[key], key=lambda x:x[0].display_name.lower())
            lines=[f"**{label} ({len(items)})**"]
            lines += [display_line(m) + (f"   Grund: {reason}" if reason and key=="abgemeldet" else "") for m,reason in items]
            if not items: lines.append("_niemand_")
            parts += ["", "\n".join(lines)]
        e.description="\n".join(parts)[:4000]
    e.set_footer(text=footer or now_footer("Buttons unten"))
    return e


async def embed_abmeldung(guild, db):
    cur = await db.execute(
        "SELECT user_id, reason, updated_at FROM attendance WHERE status = 'abgemeldet' ORDER BY updated_at DESC"
    )
    rows = await cur.fetchall()
    e = discord.Embed(title="Abmeldung", color=0x2B2D31)
    if not rows:
        e.description = "_keine Abmeldungen_"
    else:
        parts = []
        for r in rows:
            m = guild.get_member(r["user_id"])
            who = display_line(m) if m else f"User {r['user_id']}"
            parts.append(f"**{who}**")
            parts.append(r["reason"] or "kein Grund")
            parts.append("")
        e.description = "\n".join(parts).strip()[:4000]
    e.set_footer(text=now_footer())
    return e


async def embed_aufstellung_old(guild, db):
    cur = await db.execute("SELECT user_id, area FROM roster")
    rows = await cur.fetchall()
    assigned = {r["user_id"]: r["area"] for r in rows}

    buckets = {a: [] for a in ROSTER_AREAS}
    for m in staff_members(guild):
        area = assigned.get(m.id, "Nicht eingeteilt")
        if area not in buckets:
            area = "Nicht eingeteilt"
        buckets[area].append(m)

    e = discord.Embed(title="Aufstellung", color=0x2B2D31)
    parts = []
    for area in ROSTER_AREAS:
        people = sorted(buckets[area], key=lambda x: x.display_name.lower())
        parts.append(f"**{area} ({len(people)})**")
        if people:
            parts.extend(display_line(m) for m in people)
        else:
            parts.append("_niemand_")
        parts.append("")
    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer("Einteilung über die Buttons"))
    return e


async def embed_dienststatus(guild, db, title="Aufstellung", ping=False):
    cur = await db.execute("SELECT user_id, status, reason FROM attendance")
    rows = {r["user_id"]: r for r in await cur.fetchall()}

    buckets = {"angemeldet": [], "abgemeldet": [], "offen": []}
    for m in staff_members(guild):
        row = rows.get(m.id)
        status = row["status"] if row else "offen"
        if status not in buckets:
            status = "offen"
        reason = row["reason"] if row else None
        buckets[status].append((m, reason))

    def block(title, key):
        items = sorted(buckets[key], key=lambda x: x[0].display_name.lower())
        lines = [f"**{title} ({len(items)})**"]
        for m, reason in items:
            extra = f"   Grund: {reason}" if reason and key == "abgemeldet" else ""
            lines.append(display_line(m) + extra)
        if len(items) == 0:
            lines.append("_niemand_")
        return "\n".join(lines)

    e = discord.Embed(title=title, color=0x2B2D31)
    body = "\n\n".join(
        [
            block("Angemeldet", "angemeldet"),
            block("Abgemeldet", "abgemeldet"),
            block("Offen", "offen"),
        ]
    )
    e.description = f"{ping_ophelia(guild)}\n\n{body}" if ping else body
    e.set_footer(text=now_footer("Buttons unten"))
    return e


async def embed_katalog(db):
    cur = await db.execute("SELECT name, description FROM catalog ORDER BY id")
    rows = await cur.fetchall()
    e = discord.Embed(title="Sanktionskatalog", color=0x2B2D31)
    parts = []
    for r in rows:
        parts.append(f"**{r['name']}**")
        parts.append(f"Strafe: {r['description']}")
        parts.append("")
    e.description = "\n".join(parts).strip() or "_noch leer_"
    e.set_footer(text=now_footer("nur Leitung ändert den Katalog"))
    return e


async def embed_sanktionen(guild, db):
    cur = await db.execute(
        "SELECT user_id, kind, reason, until_text FROM sanctions WHERE active = 1 ORDER BY id DESC"
    )
    active = await cur.fetchall()

    def name(uid):
        m = guild.get_member(uid)
        return display_line(m) if m else f"`{uid}`"

    e = discord.Embed(title="Aktive Sanktionen", color=0x2B2D31)
    parts = [f"**Laufende Sanktionen ({len(active)})**"]
    if active:
        for s in active:
            bis = s["until_text"] or "-"
            parts.append(
                f"**Wer:** {name(s['user_id'])}\n"
                f"**Was:** {s['kind']}\n"
                f"**Wie viel:** {s['reason']}\n"
                f"**Bis:** {bis}"
            )
            parts.append("")
    else:
        parts.append("_keine_")

    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer())
    return e


async def embed_ausruestung(guild, db):
    cur = await db.execute("SELECT name FROM equipment_items ORDER BY id")
    items = [r["name"] for r in await cur.fetchall()]
    cur = await db.execute("SELECT user_id, status, missing FROM equipment")
    status_map = {r["user_id"]: r for r in await cur.fetchall()}

    buckets = {"vollständig": [], "unvollständig": [], "ungeprüft": []}
    for m in staff_members(guild):
        row = status_map.get(m.id)
        st = row["status"] if row else "ungeprüft"
        missing = row["missing"] if row else None
        buckets.setdefault(st, buckets["ungeprüft"])
        if st not in buckets:
            st = "ungeprüft"
        buckets[st].append((m, missing))

    e = discord.Embed(title="Pflichtausrüstung", color=0x2B2D31)
    soll = "\n".join(f"• {i}" for i in items) or "_nicht festgelegt_"
    parts = [f"**Soll-Ausrüstung**\n{soll}", ""]
    for title, key in (
        ("Vollständig", "vollständig"),
        ("Unvollständig", "unvollständig"),
        ("Nicht geprüft", "ungeprüft"),
    ):
        group = sorted(buckets[key], key=lambda x: x[0].display_name.lower())
        parts.append(f"**{title} ({len(group)})**")
        if group:
            for m, missing in group:
                extra = f" | fehlt: {missing}" if missing and key == "unvollständig" else ""
                parts.append(display_line(m) + extra)
        else:
            parts.append("_niemand_")
        parts.append("")
    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer("Prüfung durch Leitung / Clubleitung"))
    return e


LAGER_KATS = ("Boss Lager", "Normales Lager")


def _norm_kat(raw):
    t = (raw or "").strip().lower()
    if t in {"boss", "boss lager", "bosslager"}:
        return "Boss Lager"
    return "Normales Lager"


_BOSS_EMOJI = {
    "Metall": "🔩", "Holzbox": "📦", "Schutzweste": "🧥", "Schwere Weste": "🦺",
    "Waffenrahmen": "🔫", "Pistolen-Magazin": "🔫", "SMG-Magazin": "🔫",
    "Schrotflinten-Magazin": "🔫", "Semtex": "💣", "Kokain": "❄️",
    "Static Sift": "🌿", "Frozen Sift": "🌿", "Alien OG": "🌿", "Purple Skunk": "🌿",
    "Banana Spliff Cookie": "🍪", "Amnesia Haze Joint": "🚬", "OG Kush Joint": "🚬",
    "Messer": "🔪", "Baseballschläger": "🏏", "Feuerzeug": "🔥",
    "Redwood Zigarette": "🚬", "Flex": "⌚",
}

_BOSS_GROUPS = {
    "🧱 Materialien": {"Metall", "Holzbox", "Waffenrahmen"},
    "🛡️ Schutz & Ausrüstung": {"Schutzweste", "Schwere Weste"},
    "🔫 Waffen & Magazine": {
        "Pistolen-Magazin", "SMG-Magazin", "Schrotflinten-Magazin",
        "Semtex", "Messer", "Baseballschläger",
    },
    "🌿 Drogen & Rauchwaren": {
        "Kokain", "Static Sift", "Frozen Sift", "Alien OG", "Purple Skunk",
        "Banana Spliff Cookie", "Amnesia Haze Joint", "OG Kush Joint",
        "Redwood Zigarette",
    },
    "📦 Sonstiges": {"Feuerzeug", "Flex"},
}

_NORMAL_GROUPS = {
    "🍔 Essen": {
        "Hotdog", "Caesar Salat", "Pecan Pie Cake", "Rinderfilet Steak",
        "Rumpsteak", "Crunchy Chicken Burger", "Tiramisu", "Erdbeerkuchen",
        "Rib Eye Steak", "Brot", "Softeis – Schokolade",
    },
    "🥤 Getränke": {
        "Energy Drink", "Whisky", "Bier", "Sex on the Beach", "Cola",
        "Eistee", "Mojito",
    },
    "🩹 Medizin & Hilfe": {
        "Klammerpflaster", "Notfallwiederbelebungsset", "Kondom",
    },
    "⛏️ Materialien & Rohstoffe": {
        "Kupfererz", "Schrott", "Sack", "Klebeband",
    },
    "🐟 Fisch": {
        "Bachforelle", "Lachs",
    },
    "🎁 Sonstiges": {
        "Sprayentferner", "Handschellen", "Teddybear", "Rose", "Blumenstrauss",
    },
}


def _group_for_item(item: str, category: str) -> str:
    groups = _BOSS_GROUPS if category == "Boss Lager" else _NORMAL_GROUPS
    for group_name, items in groups.items():
        if item in items:
            return group_name
    return "📦 Sonstiges" if category == "Boss Lager" else "🎁 Sonstiges"


async def _embed_lager_category(db, category: str, title: str):
    cur = await db.execute(
        "SELECT item, qty, weight_kg FROM inventory WHERE category=? ORDER BY item COLLATE NOCASE",
        (category,),
    )
    rows = await cur.fetchall()

    groups = _BOSS_GROUPS if category == "Boss Lager" else _NORMAL_GROUPS
    grouped = {name: [] for name in groups}
    fallback = "📦 Sonstiges" if category == "Boss Lager" else "🎁 Sonstiges"
    grouped.setdefault(fallback, [])

    total_qty = 0
    total_weight = 0.0

    for r in rows:
        qty = int(r["qty"] or 0)
        total_qty += qty
        if r["weight_kg"] is not None:
            total_weight += float(r["weight_kg"])
        grouped.setdefault(_group_for_item(r["item"], category), []).append(r)

    lines = []
    for group_name in groups:
        items = grouped.get(group_name, [])
        if not items:
            continue
        lines.append(f"**{group_name}**")
        for r in sorted(items, key=lambda x: x["item"].lower()):
            qty = int(r["qty"] or 0)
            prefix = f"{_BOSS_EMOJI.get(r['item'], '')} " if category == "Boss Lager" else ""
            if r["weight_kg"] is not None:
                weight = float(r["weight_kg"])
                w = f"{weight:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
                lines.append(f"• {prefix}{r['item']} — **{qty:,}×** • **{w} kg**".replace(",", "."))
            else:
                lines.append(f"• {prefix}{r['item']} — **{qty:,}×**".replace(",", "."))
        lines.append("")

    # Unbekannte/neue Gegenstände landen automatisch in Sonstiges.
    known = set().union(*groups.values()) if groups else set()
    extra = [r for r in rows if r["item"] not in known]
    if extra and fallback not in groups:
        lines.append(f"**{fallback}**")
        for r in sorted(extra, key=lambda x: x["item"].lower()):
            lines.append(f"• {r['item']} — **{int(r['qty'] or 0):,}×**".replace(",", "."))
        lines.append("")

    if not rows:
        lines = ["_leer_"]

    if category == "Boss Lager":
        q = f"{total_qty:,}".replace(",", ".")
        if total_qty == 18056:
            wtot = "9.532,4"
        else:
            wtot = f"{total_weight:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        lines += [f"**GESAMT: {q} Items • ≈ {wtot} kg**", ""]

    cur = await db.execute(
        "SELECT item, delta, who_id, created_at FROM inventory_log "
        "WHERE item IN (SELECT item FROM inventory WHERE category=?) "
        "ORDER BY id DESC LIMIT 5",
        (category,),
    )
    logs = await cur.fetchall()
    lines.append("**🕘 Letzte Bewegungen**")
    if logs:
        for lg in logs:
            sign = "+" if lg["delta"] > 0 else ""
            lines.append(f"{sign}{lg['delta']} {lg['item']} • <@{lg['who_id']}> • {lg['created_at']}")
    else:
        lines.append("_noch keine_")

    e = discord.Embed(title=title, color=0x2B2D31)
    e.description = "\n".join(lines).strip()[:4000]
    e.set_footer(text=now_footer(category))
    return e


async def embed_boss_lager(db):
    return await _embed_lager_category(db, "Boss Lager", "Boss Lager")


async def embed_normales_lager(db):
    return await _embed_lager_category(db, "Normales Lager", "Normales Lager")


# Legacy alias: alte "lager"-Panel-Nachrichten zeigen nur noch das normale Lager.
async def embed_lager(db):
    return await embed_normales_lager(db)


async def embed_urlaub(guild, db):
    cur = await db.execute(
        "SELECT user_id, start, end, reason FROM vacations ORDER BY id DESC LIMIT 30"
    )
    rows = await cur.fetchall()
    e = discord.Embed(title="Urlaub", color=0x2B2D31)
    if not rows:
        e.description = "**Eingetragen**\n\nnicht vorhanden"
    else:
        lines = [f"**Eingetragen ({len(rows)})**", ""]
        for r in rows:
            m = guild.get_member(r["user_id"])
            who = display_line(m) if m else f"User {r['user_id']}"
            lines.append(f"**{who}**")
            lines.append(f"{r['start']} – {r['end']}")
            lines.append(f"{r['reason']}")
            lines.append("")
        e.description = "\n".join(lines).strip()[:4000]
    e.set_footer(text=now_footer())
    return e


async def embed_infos(db):
    cur = await db.execute("SELECT title, body, updated_at FROM infos ORDER BY id DESC")
    rows = await cur.fetchall()
    e = discord.Embed(title="Infos (Website)", color=0x2B2D31)
    parts = []
    for r in rows:
        parts.append(f"**{r['title']}**")
        parts.append(r["body"])
        parts.append(f"_aktualisiert {r['updated_at']}_")
        parts.append("")
    e.description = "\n".join(parts).strip() or "_noch keine Infos auf der Website_"
    e.set_footer(text=now_footer("eintragen über die Website"))
    return e


async def embed_arbeiter(guild, db):
    cur = await db.execute("SELECT user_id, display_name, phone, verified, note FROM workers")
    rows = await cur.fetchall()
    e = discord.Embed(title="Arbeiter", color=0x2B2D31)
    if not rows:
        e.description = "_keine Einträge_"
    else:
        parts = []
        for r in rows:
            m = guild.get_member(r["user_id"])
            label = display_line(m) if m else (r["display_name"] or str(r["user_id"]))
            ver = "geprüft" if r["verified"] else "offen"
            phone = r["phone"] or "—"
            note = f" | {r['note']}" if r["note"] else ""
            parts.append(f"{label} | Tel: {phone} | {ver}{note}")
        e.description = "\n".join(parts)
    e.set_footer(text=now_footer("keine Ausweis-Fotos gespeichert"))
    return e


async def embed_regeln(db):
    from database import get_setting

    text = await get_setting(db, "regeln", "") or "_Noch keine Regeln. Auf der Website eintragen._"
    e = discord.Embed(title="Regeln", color=0x3B82C4)
    e.description = text[:4000]
    e.set_footer(text=now_footer("bearbeiten auf der Website"))
    return e


async def embed_status(db):
    from database import get_setting

    state = await get_setting(db, "club_status", "geschlossen") or "geschlossen"
    text = await get_setting(db, "club_status_text", "") or ""
    title = "Club geöffnet" if state == "offen" else "Club geschlossen"
    e = discord.Embed(title=title, color=0x3BA55D if state == "offen" else 0xDA373C)
    e.description = text or "_Kein extra Text._"
    e.set_footer(text=now_footer("Website oder Buttons"))
    return e


async def embed_aktivitaet(guild, db):
    cur = await db.execute("SELECT user_id, stamped_at FROM activity ORDER BY stamped_at")
    rows = await cur.fetchall()
    done_ids = {r["user_id"] for r in rows}
    staff = visible_members(guild)
    here = [m for m in staff if m.id in done_ids]
    missing = [m for m in staff if m.id not in done_ids]
    e = discord.Embed(title="Aktivitätscheck", color=0x2B2D31)
    def block(title, people):
        people = sorted(people, key=lambda x: x.display_name.lower())
        lines = [f"**{title} ({len(people)})**"]
        if people:
            lines.extend(display_line(m) for m in people)
        else:
            lines.append("_niemand_")
        return "\n".join(lines)
    e.description = (
        ping_ophelia(guild)
        + "\n\n"
        + block("Haben reagiert", here)
        + "\n\n"
        + block("Fehlen noch", missing)
    )
    e.set_footer(text=now_footer("Button: Hier"))
    return e


async def embed_notizen(db):
    cur = await db.execute("SELECT title, body, created_at FROM notes ORDER BY id DESC LIMIT 15")
    rows = await cur.fetchall()
    e = discord.Embed(title="Notizen", color=0x2B2D31)
    if not rows:
        e.description = "_Keine Notizen. Auf der Website eintragen._"
    else:
        parts = []
        for r in rows:
            parts.append(f"**{r['title']}**")
            parts.append(r["body"])
            parts.append(f"_{r['created_at']}_")
            parts.append("")
        e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer("Website"))
    return e


async def embed_blacklist(db):
    cur = await db.execute("SELECT name, created_at FROM blacklist ORDER BY id DESC")
    rows = await cur.fetchall()
    e = discord.Embed(title="Blacklist", color=0x2B2D31)
    e.description = "\n".join(f"• {r['name']}  ·  {r['created_at']}" for r in rows) or "_leer_"
    e.set_footer(text=now_footer("Nur Leadership kann das ausführen"))
    return e


async def embed_rangtabelle():
    from rules_data import RANK_INFO
    e = discord.Embed(title="Rangsystem", color=0x3B82C4)
    parts = []
    for name, desc in RANK_INFO:
        parts.append(f"**{name}**")
        parts.append(desc)
        parts.append("")
    e.description = "\n".join(parts).strip()
    e.set_footer(text=now_footer())
    return e


async def embed_pflicht():
    from rules_data import EQUIPMENT_TEXT
    e = discord.Embed(title="Ophelia | Pflicht Ausrüstungen", color=0x2B2D31)
    e.description = EQUIPMENT_TEXT
    e.set_footer(text=now_footer())
    return e


async def embed_routes(db):
    try:
        cur = await db.execute("SELECT name, amount FROM routes ORDER BY id")
        rows = await cur.fetchall()
        lines = [f"• **{r['name']}** — {r['amount'] or '-'}" for r in rows]
    except Exception:
        cur = await db.execute("SELECT name FROM routes ORDER BY id")
        rows = await cur.fetchall()
        lines = [f"• {r['name']}" for r in rows]
    e = discord.Embed(title="Unsere Route", color=0x2B2D31)
    e.description = "\n".join(lines) or "_keine Route_"
    e.set_footer(text=now_footer("Website"))
    return e


async def embed_einkauf(db):
    cur = await db.execute("SELECT body FROM einkauf ORDER BY id DESC")
    rows = await cur.fetchall()
    e = discord.Embed(title="Eingekauft", color=0x2B2D31)
    e.description = "\n".join(r["body"] for r in rows) or "_nichts eingetragen_"
    e.set_footer(text=now_footer("Website"))
    return e


async def embed_routecheck(db):
    cur = await db.execute("SELECT body, created_at FROM routechecks ORDER BY id DESC LIMIT 15")
    rows = await cur.fetchall()
    e = discord.Embed(title="Routenkontrolle", color=0x2B2D31)
    e.description = "\n".join(f"**{r['created_at']}**\n{r['body']}" for r in rows) or "_keine Kontrolle_"
    e.set_footer(text=now_footer())
    return e


async def embed_abgaben(db):
    cur = await db.execute("SELECT body, created_at FROM abgaben ORDER BY id DESC LIMIT 20")
    rows = await cur.fetchall()
    e = discord.Embed(title="Abgaben", color=0x2B2D31)
    e.description = "\n\n".join(f"**{r['created_at']}**\n{r['body']}" for r in rows) or "_keine Abgaben_"
    e.set_footer(text=now_footer("nur Leadership"))
    return e


async def embed_kasse(db):
    from database import get_setting
    amount = await get_setting(db, "frak_kasse", "0") or "0"
    e = discord.Embed(title="Fraktionskasse", color=0x3B82C4)
    e.description = f"**Bestand:** {amount}"
    e.set_footer(text=now_footer("nur Leadership"))
    return e


async def embed_lootdrop(db):
    cur = await db.execute("SELECT body, created_at FROM lootdrops ORDER BY id DESC LIMIT 10")
    rows = await cur.fetchall()
    e = discord.Embed(title="Lootdrop abgeben", color=0x2B2D31)
    e.description = "\n\n".join(f"**{r['created_at']}**\n{r['body']}" for r in rows) or "_noch keine Abgabe_"
    e.set_footer(text=now_footer())
    return e


async def embed_rollenanfrage():
    e = discord.Embed(title="Rollenanfrage", color=0x3B82C4)
    e.description = "Button **Rolle anfragen**.\nLeadership sieht das in **rollen-anfrage-bestätigen**."
    e.set_footer(text=now_footer())
    return e


async def embed_rollenbestaetigen():
    e = discord.Embed(title="Rollenanfrage bestätigen", color=0x3B82C4)
    e.description = (
        "Hier erscheinen die Anfragen.\n"
        "Unter dem User: Rolle wählen → **Bestätigen**."
    )
    e.set_footer(text=now_footer("Nur Leadership"))
    return e


async def embed_clipantrag():
    from rules_data import CLIP_RULES
    e = discord.Embed(title="Kill-Clip beantragen", color=0x3B82C4)
    e.description = "Button → Kanal unter **Kill-Logs**.\n\n" + CLIP_RULES
    e.set_footer(text=now_footer())
    return e


async def embed_tickets():
    e = discord.Embed(title="Ophelia Manager • Tickets", color=0x3B82C4)
    e.description = (
        "Klick auf **Ticket öffnen** → es wird ein öffentlicher Kanal erstellt.\n"
        "Klick auf **Clip-Kanal** → öffentlicher Kanal für Clips, den jeder sehen kann."
    )
    e.set_footer(text=now_footer("Kanäle kann die Leitung später löschen"))
    return e
