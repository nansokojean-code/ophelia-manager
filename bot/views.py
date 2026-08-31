from datetime import datetime

import discord

from ranks import ROSTER_AREAS, is_leader, is_officer, is_staff


def stamp():
    return datetime.now().strftime("%d.%m.%Y %H:%M")


class ConfirmDenied(discord.ui.View):
    def __init__(self, text):
        super().__init__(timeout=30)
        self.text = text


class AbmeldenModal(discord.ui.Modal, title="Abmelden"):
    von = discord.ui.TextInput(label="Von wann", required=True, max_length=40)
    bis = discord.ui.TextInput(label="Bis wann", required=True, max_length=40)
    grund = discord.ui.TextInput(label="Warum", style=discord.TextStyle.paragraph, required=True, max_length=200)
    wer = discord.ui.TextInput(label="Wer (leer = du)", required=False, max_length=40)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        who = str(self.wer).strip() or str(interaction.user)
        text = f"{self.von} – {self.bis} | {self.grund} | {who}"
        await self.bot.db.execute(
            """
            INSERT INTO attendance(user_id, status, reason, updated_at)
            VALUES(?, 'abgemeldet', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET status='abgemeldet', reason=excluded.reason, updated_at=excluded.updated_at
            """,
            (interaction.user.id, text, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst", "aufstellung"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} abgemeldet: {text}")
        await interaction.response.send_message("Du bist **abgemeldet**.", ephemeral=True)


class SanktionModal(discord.ui.Modal, title="Sanktion eintragen"):
    person_id = discord.ui.TextInput(label="Discord-ID der Person", required=True, max_length=25)
    kind = discord.ui.TextInput(label="Regel-Nr (z.B. 2)", required=True, max_length=80)
    dauer = discord.ui.TextInput(label="Bis wann", required=False, max_length=80)
    grund = discord.ui.TextInput(label="Wie viel / Extra", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        await self.bot.db.execute(
            """
            INSERT INTO sanctions(user_id, kind, reason, until_text, by_id, active, created_at)
            VALUES(?, ?, ?, ?, ?, 1, ?)
            """,
            (uid, str(self.kind), str(self.grund), str(self.dauer) or None, interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["sanktionen"])
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} hat Sanktion gegen <@{uid}> eingetragen: {self.kind} – {self.grund}",
        )
        await interaction.response.send_message("Sanktion eingetragen.", ephemeral=True)


class WarnModal(discord.ui.Modal, title="Verwarnung"):
    person_id = discord.ui.TextInput(label="Discord-ID der Person", required=True, max_length=25)
    grund = discord.ui.TextInput(label="Grund", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO warnings(user_id, reason, by_id, created_at) VALUES(?, ?, ?, ?)",
            (uid, str(self.grund), interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["sanktionen"])
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} hat <@{uid}> verwarnt: {self.grund}",
        )
        await interaction.response.send_message("Verwarnung eingetragen.", ephemeral=True)


class LagerModal(discord.ui.Modal):
    item = discord.ui.TextInput(label="Was (genau wie im Lager)", required=True, max_length=80)
    menge = discord.ui.TextInput(label="Wie viel (Zahl)", required=True, max_length=8)
    wer = discord.ui.TextInput(
        label="Wer (leer = du selbst, sonst Discord-ID)",
        required=False,
        max_length=25,
    )

    def __init__(self, bot, direction: int):
        title = "Reinlegen" if direction > 0 else "Rausnehmen"
        super().__init__(title=title)
        self.bot = bot
        self.direction = direction

    async def on_submit(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        try:
            qty = int(str(self.menge).strip())
            if qty <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Menge muss eine Zahl größer 0 sein.", ephemeral=True)

        item = str(self.item).strip()
        who = interaction.user.id
        if str(self.wer).strip():
            if not is_officer(interaction.user):
                return await interaction.response.send_message("Nur Leitung darf eine andere Person eintragen.", ephemeral=True)
            try:
                who = int(str(self.wer).strip())
            except ValueError:
                return await interaction.response.send_message("Ungültige ID bei Wer.", ephemeral=True)

        cur = await self.bot.db.execute("SELECT qty FROM inventory WHERE item = ?", (item,))
        row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message(
                f"`{item}` gibt es nicht im Lager. Name genau wie in der Liste schreiben.",
                ephemeral=True,
            )
        new_qty = row["qty"] + (qty * self.direction)
        if new_qty < 0:
            return await interaction.response.send_message(
                f"Nicht genug Bestand. Aktuell: {row['qty']}.",
                ephemeral=True,
            )
        await self.bot.db.execute("UPDATE inventory SET qty = ? WHERE item = ?", (new_qty, item))
        await self.bot.db.execute(
            "INSERT INTO inventory_log(item, delta, who_id, created_at) VALUES(?, ?, ?, ?)",
            (item, qty * self.direction, who, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["lager"])
        verb = "reingelegt" if self.direction > 0 else "rausgenommen"
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention}: {qty}× {item} {verb} (Wer: <@{who}>). Neu: {new_qty}",
        )
        await interaction.response.send_message(
            f"**{qty}× {item}** {verb}. Neuer Bestand: **{new_qty}**.",
            ephemeral=True,
        )


class LagerNeuModal(discord.ui.Modal, title="Neuen Gegenstand anlegen"):
    item = discord.ui.TextInput(label="Name", required=True, max_length=80)
    kategorie = discord.ui.TextInput(label="Kategorie", required=True, max_length=40, default="Sonstiges")
    menge = discord.ui.TextInput(label="Startbestand", required=True, max_length=8, default="0")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
        try:
            qty = int(str(self.menge).strip())
        except ValueError:
            return await interaction.response.send_message("Startbestand muss eine Zahl sein.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO inventory(item, category, qty) VALUES(?, ?, ?)",
            (str(self.item).strip(), str(self.kategorie).strip(), qty),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["lager"])
        await interaction.response.send_message("Gegenstand angelegt.", ephemeral=True)


class RosterModal(discord.ui.Modal, title="Aufstellung setzen"):
    person_id = discord.ui.TextInput(label="Discord-ID der Person", required=True, max_length=25)
    bereich = discord.ui.TextInput(
        label="Bereich",
        required=True,
        max_length=40,
        placeholder="Bar / Tür / Service / Büro / Nicht eingeteilt",
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        area = str(self.bereich).strip()
        if area not in ROSTER_AREAS:
            return await interaction.response.send_message(
                "Bereich muss einer von: " + ", ".join(ROSTER_AREAS),
                ephemeral=True,
            )
        await self.bot.db.execute(
            "INSERT INTO roster(user_id, area) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET area=excluded.area",
            (uid, area),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["aufstellung"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat <@{uid}> nach **{area}** eingeteilt.")
        await interaction.response.send_message("Aufstellung aktualisiert.", ephemeral=True)


class EquipModal(discord.ui.Modal, title="Ausrüstung setzen"):
    person_id = discord.ui.TextInput(label="Discord-ID der Person", required=True, max_length=25)
    status = discord.ui.TextInput(
        label="Status",
        required=True,
        placeholder="vollständig / unvollständig / ungeprüft",
        max_length=20,
    )
    fehlt = discord.ui.TextInput(label="Was fehlt (wenn unvollständig)", required=False, max_length=120)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        st = str(self.status).strip().lower()
        if st not in {"vollständig", "unvollständig", "ungeprüft"}:
            return await interaction.response.send_message("Status ungültig.", ephemeral=True)
        await self.bot.db.execute(
            """
            INSERT INTO equipment(user_id, status, missing) VALUES(?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, missing=excluded.missing
            """,
            (uid, st, str(self.fehlt) or None),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["ausruestung"])
        await interaction.response.send_message("Ausrüstung aktualisiert.", ephemeral=True)


class UrlaubModal(discord.ui.Modal, title="Urlaub beantragen"):
    start = discord.ui.TextInput(label="Von (z.B. 01.09.2026)", required=True, max_length=20)
    ende = discord.ui.TextInput(label="Bis (z.B. 10.09.2026)", required=True, max_length=20)
    grund = discord.ui.TextInput(label="Begründung", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "INSERT INTO vacations(user_id, start, end, reason, status, created_at) VALUES(?, ?, ?, ?, 'beantragt', ?)",
            (interaction.user.id, str(self.start), str(self.ende), str(self.grund), stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["urlaub"])
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} hat Urlaub beantragt: {self.start} – {self.ende} ({self.grund})",
        )
        await interaction.response.send_message("Urlaub beantragt. Leitung muss genehmigen.", ephemeral=True)


class DienstView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Anmelden", style=discord.ButtonStyle.success, custom_id="dienst:an")
    async def anmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Nur Mitarbeiter.", ephemeral=True)
        await self.bot.db.execute(
            """
            INSERT INTO attendance(user_id, status, reason, updated_at)
            VALUES(?, 'angemeldet', NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET status='angemeldet', reason=NULL, updated_at=excluded.updated_at
            """,
            (interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat sich angemeldet.")
        await interaction.response.send_message("Du bist jetzt **angemeldet**.", ephemeral=True)

    @discord.ui.button(label="Abmelden", style=discord.ButtonStyle.danger, custom_id="dienst:ab")
    async def abmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Nur Mitarbeiter.", ephemeral=True)
        await interaction.response.send_modal(AbmeldenModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="dienst:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["dienst"])
        await interaction.response.send_message("Liste aktualisiert.", ephemeral=True)


class AufstellungView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Einteilen", style=discord.ButtonStyle.primary, custom_id="roster:set")
    async def setzen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await interaction.response.send_modal(RosterModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="roster:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["aufstellung"])
        await interaction.response.send_message("Liste aktualisiert.", ephemeral=True)


class LagerView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Reinlegen", style=discord.ButtonStyle.success, custom_id="lager:in")
    async def rein(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LagerModal(self.bot, +1))

    @discord.ui.button(label="Rausnehmen", style=discord.ButtonStyle.danger, custom_id="lager:out")
    async def raus(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LagerModal(self.bot, -1))

    @discord.ui.button(label="Gegenstand anlegen", style=discord.ButtonStyle.primary, custom_id="lager:new")
    async def neu(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
        await interaction.response.send_modal(LagerNeuModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="lager:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["lager"])
        await interaction.response.send_message("Lager aktualisiert.", ephemeral=True)


class SanktionView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Verwarnen", style=discord.ButtonStyle.secondary, custom_id="san:warn")
    async def warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await interaction.response.send_modal(WarnModal(self.bot))

    @discord.ui.button(label="Sanktion", style=discord.ButtonStyle.danger, custom_id="san:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        await interaction.response.send_modal(SanktionModal(self.bot))

    @discord.ui.button(label="Bezahlt", style=discord.ButtonStyle.success, custom_id="san:pay")
    async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        await interaction.response.send_modal(BezahltModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="san:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["sanktionen", "katalog"])
        await interaction.response.send_message("Aktualisiert.", ephemeral=True)


class AusruestungView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Status setzen", style=discord.ButtonStyle.primary, custom_id="eq:set")
    async def setzen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await interaction.response.send_modal(EquipModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="eq:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["ausruestung"])
        await interaction.response.send_message("Aktualisiert.", ephemeral=True)


class UrlaubView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Beantragen", style=discord.ButtonStyle.primary, custom_id="urlaub:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UrlaubModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="urlaub:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["urlaub"])
        await interaction.response.send_message("Aktualisiert.", ephemeral=True)


class RangView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="rang:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, ["rang", "mitarbeiter"])
        await interaction.response.send_message("Aktualisiert.", ephemeral=True)


class SimpleRefreshView(discord.ui.View):
    def __init__(self, bot, panels):
        super().__init__(timeout=None)
        self.bot = bot
        self.panels = panels

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="simple:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.refresh_panels(interaction.guild, self.panels)
        await interaction.response.send_message("Aktualisiert.", ephemeral=True)


async def _get_or_create_category(guild: discord.Guild, name: str):
    for cat in guild.categories:
        if cat.name.lower() == name.lower():
            return cat
    return await guild.create_category(name)


class TicketView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ticket öffnen", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cat = await _get_or_create_category(interaction.guild, "Tickets")
        safe = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c in "-_")[:20] or "user"
        ch = await interaction.guild.create_text_channel(
            name=f"ticket-{safe}",
            category=cat,
            topic=f"Ticket von {interaction.user} ({interaction.user.id})",
        )
        await ch.send(
            f"{interaction.user.mention} hat ein Ticket geöffnet. Jeder auf dem Server kann diesen Kanal sehen."
        )
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat {ch.mention} geöffnet.")
        await interaction.followup.send(f"Ticket erstellt: {ch.mention}", ephemeral=True)

    @discord.ui.button(label="Clip-Kanal", style=discord.ButtonStyle.secondary, custom_id="ticket:clip")
    async def open_clip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cat = await _get_or_create_category(interaction.guild, "Clips")
        safe = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c in "-_")[:20] or "user"
        ch = await interaction.guild.create_text_channel(
            name=f"clip-{safe}",
            category=cat,
            topic=f"Clips von {interaction.user}",
        )
        await ch.send(f"{interaction.user.mention} — hier kannst du Clips posten. Der Kanal ist öffentlich.")
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat Clip-Kanal {ch.mention} erstellt.")
        await interaction.followup.send(f"Clip-Kanal erstellt: {ch.mention}", ephemeral=True)


class AktivitaetView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Hier", style=discord.ButtonStyle.success, custom_id="akt:hier")
    async def hier(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db.execute(
            "INSERT INTO activity(user_id, stamped_at) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET stamped_at=excluded.stamped_at",
            (interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["aktivitaet"])
        await interaction.response.send_message("Eingecheckt.", ephemeral=True)

    @discord.ui.button(label="Check neu starten", style=discord.ButtonStyle.danger, custom_id="akt:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await self.bot.db.execute("DELETE FROM activity")
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["aktivitaet"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat den Aktivitätscheck neu gestartet.")
        await interaction.response.send_message("Check zurückgesetzt.", ephemeral=True)


class StatusView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Öffnen", style=discord.ButtonStyle.success, custom_id="club:open")
    async def open_club(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        import database as dbmod
        await dbmod.set_setting(self.bot.db, "club_status", "offen")
        await self.bot.refresh_panels(interaction.guild, ["status"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat den Club geöffnet.")
        await interaction.response.send_message("Status: offen.", ephemeral=True)

    @discord.ui.button(label="Schließen", style=discord.ButtonStyle.danger, custom_id="club:close")
    async def close_club(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        import database as dbmod
        await dbmod.set_setting(self.bot.db, "club_status", "geschlossen")
        await self.bot.refresh_panels(interaction.guild, ["status"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat den Club geschlossen.")
        await interaction.response.send_message("Status: geschlossen.", ephemeral=True)


class BezahltModal(discord.ui.Modal, title="Sanktion bezahlt"):
    person_id = discord.ui.TextInput(label="Discord-ID der Person", required=True, max_length=25)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        await self.bot.db.execute("UPDATE sanctions SET active = 0 WHERE user_id = ? AND active = 1", (uid,))
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["sanktionen"])
        await interaction.response.send_message("Als bezahlt markiert.", ephemeral=True)


class BlacklistModal(discord.ui.Modal, title="Blacklist"):
    name = discord.ui.TextInput(label="Name", required=True, max_length=80)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO blacklist(name, by_id, created_at) VALUES(?, ?, ?)",
            (str(self.name).strip(), interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["blacklist"])
        await interaction.response.send_message("Auf die Blacklist gesetzt.", ephemeral=True)


class RolleGebenModal(discord.ui.Modal, title="Rolle vergeben"):
    person_id = discord.ui.TextInput(label="Discord-ID", required=True, max_length=25)
    rang = discord.ui.TextInput(label="Rang-Name genau", required=True, max_length=80, placeholder="Rang 1 – Associate")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        from ranks import RANK_ROLE_NAMES
        try:
            uid = int(str(self.person_id).strip())
        except ValueError:
            return await interaction.response.send_message("Ungültige ID.", ephemeral=True)
        rname = str(self.rang).strip()
        if rname not in RANK_ROLE_NAMES:
            return await interaction.response.send_message("Unbekannter Rang.", ephemeral=True)
        member = interaction.guild.get_member(uid)
        role = discord.utils.get(interaction.guild.roles, name=rname)
        if not member or not role:
            return await interaction.response.send_message("User oder Rolle nicht gefunden.", ephemeral=True)
        try:
            to_remove = [r for r in member.roles if r.name in RANK_ROLE_NAMES and r != role]
            if to_remove:
                await member.remove_roles(*to_remove)
            await member.add_roles(role, reason=f"Rollen-Anfrage durch {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("Bot-Rolle zu weit unten.", ephemeral=True)
        await self.bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "dienst"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} gab {member.mention} **{rname}**")
        await interaction.response.send_message(f"{member.mention} ist jetzt **{rname}**.", ephemeral=True)


class LootModal(discord.ui.Modal, title="Lootdrop abgeben"):
    body = discord.ui.TextInput(label="Was (wie im Beispiel)", style=discord.TextStyle.paragraph, required=True, max_length=800)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "INSERT INTO lootdrops(body, created_at) VALUES(?, ?)",
            (str(self.body), stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["lootdrop"])
        await interaction.response.send_message("Lootdrop eingetragen.", ephemeral=True)


class RouteCheckModal(discord.ui.Modal, title="Routenkontrolle"):
    body = discord.ui.TextInput(
        label="Route, wer, wie viele, Familie/Arbeiter",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500,
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "INSERT INTO routechecks(body, created_at) VALUES(?, ?)",
            (str(self.body), stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["routecheck"])
        await interaction.response.send_message("Kontrolle eingetragen.", ephemeral=True)


class BlacklistView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Blacklist", style=discord.ButtonStyle.danger, custom_id="bl:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        await interaction.response.send_modal(BlacklistModal(self.bot))


class RolleAnfrageView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Rolle anfragen", style=discord.ButtonStyle.primary, custom_id="role:ask")
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.log(interaction.guild, f"{interaction.user.mention} fragt eine Rolle an.")
        await interaction.response.send_message("Anfrage ist raus. Leadership vergibt die Rolle.", ephemeral=True)

    @discord.ui.button(label="Rolle vergeben", style=discord.ButtonStyle.success, custom_id="role:give")
    async def give(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
        await interaction.response.send_modal(RolleGebenModal(self.bot))


class ClipAntragView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Kill-Clip beantragen", style=discord.ButtonStyle.primary, custom_id="clip:ask")
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        from rules_data import CLIP_RULES
        cat = None
        for c in interaction.guild.categories:
            if c.name.lower() in {"kill-logs", "kill logs", "killlogs"}:
                cat = c
                break
        if cat is None:
            cat = await interaction.guild.create_category("Kill-Logs")
        safe = "".join(ch for ch in interaction.user.name.lower() if ch.isalnum() or ch in "-_")[:18] or "user"
        channel = await interaction.guild.create_text_channel(name=f"clip-{safe}", category=cat)
        await self.bot.db.execute(
            "INSERT INTO clip_channels(user_id, channel_id) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET channel_id=excluded.channel_id",
            (interaction.user.id, channel.id),
        )
        await self.bot.db.commit()
        await channel.send(f"{interaction.user.mention}\n{CLIP_RULES}")
        await interaction.response.send_message(f"Kanal: {channel.mention}", ephemeral=True)


class LootView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Abgeben", style=discord.ButtonStyle.success, custom_id="loot:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LootModal(self.bot))


class RouteCheckView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Kontrolle eintragen", style=discord.ButtonStyle.primary, custom_id="rc:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouteCheckModal(self.bot))
