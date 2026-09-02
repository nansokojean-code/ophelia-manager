from datetime import datetime

import discord

from ranks import ROSTER_AREAS, can_blacklist, can_route, is_high, is_leader, is_officer, is_staff


def stamp():
    return datetime.now().strftime("%d.%m.%Y %H:%M")


LEAD_MSG = "Nur Leadership kann das ausführen."


async def lead_repost(interaction, bot, key):
    if not is_high(interaction.user):
        return await interaction.response.send_message(LEAD_MSG, ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await bot.repost_panel(interaction.guild, key)
    await interaction.followup.send("Nachricht neu gesendet.", ephemeral=True)


def _stamp_unused():
    return datetime.now().strftime("%d.%m.%Y %H:%M")


class ConfirmDenied(discord.ui.View):
    def __init__(self, text):
        super().__init__(timeout=30)
        self.text = text


class AbmeldenModal(discord.ui.Modal, title="Abmelden"):
    von = discord.ui.TextInput(label="Von wann", required=True, max_length=40)
    bis = discord.ui.TextInput(label="Bis wann", required=True, max_length=40)
    grund = discord.ui.TextInput(label="Grund", style=discord.TextStyle.paragraph, required=True, max_length=200)

    def __init__(self, bot, person: discord.Member):
        super().__init__()
        self.bot = bot
        self.person = person

    async def on_submit(self, interaction: discord.Interaction):
        text = f"{self.person.mention} | {self.von} – {self.bis} | {self.grund}"
        await self.bot.db.execute(
            """
            INSERT INTO attendance(user_id, status, reason, updated_at)
            VALUES(?, 'abgemeldet', ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET status='abgemeldet', reason=excluded.reason, updated_at=excluded.updated_at
            """,
            (self.person.id, text, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst", "aufstellung"])
        await self.bot.log(interaction.guild, text, "Abmeldung")
        await interaction.response.send_message(f"{self.person.mention} ist abgemeldet.", ephemeral=True)


class SanktionModal(discord.ui.Modal, title="Sanktion eintragen"):
    kind = discord.ui.TextInput(label="Regel-Nr (z.B. 2)", required=True, max_length=80)
    dauer = discord.ui.TextInput(label="Bis wann", required=False, max_length=80)
    grund = discord.ui.TextInput(label="Wie viel / Extra", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot, person: discord.Member):
        super().__init__()
        self.bot = bot
        self.person = person

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        uid = self.person.id
        await self.bot.db.execute(
            """
            INSERT INTO sanctions(user_id, kind, reason, until_text, by_id, active, created_at)
            VALUES(?, ?, ?, ?, ?, 1, ?)
            """,
            (uid, str(self.kind), str(self.grund), str(self.dauer) or None, interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        cur = await self.bot.db.execute("SELECT last_insert_rowid() AS i")
        sid = (await cur.fetchone())["i"]
        e = discord.Embed(title="Sanktion", color=0xC0392B)
        e.description = (
            f"**Wer:** {self.person.mention}\n"
            f"**Regel:** {self.kind}\n"
            f"**Wie viel:** {self.grund}\n"
            f"**Bis:** {self.dauer or '-'}"
        )
        e.set_footer(text=f"SID:{sid}")
        await interaction.channel.send(embed=e, view=SanktionPayView())
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} hat Sanktion gegen {self.person.mention}: {self.kind} – {self.grund}",
            "Sanktionen",
        )
        await interaction.response.send_message(f"Sanktion für {self.person.mention} gepostet.", ephemeral=True)


class SanktionPayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Bezahlt", style=discord.ButtonStyle.success, custom_id="san:paymsg")
    async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        sid = None
        if interaction.message.embeds:
            foot = interaction.message.embeds[0].footer.text or ""
            if "SID:" in foot:
                try:
                    sid = int(foot.split("SID:")[1].split()[0])
                except ValueError:
                    sid = None
        if sid:
            await interaction.client.db.execute("UPDATE sanctions SET active = 0 WHERE id = ?", (sid,))
            await interaction.client.db.commit()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass
        await interaction.response.send_message("Sanktion als bezahlt gelöscht.", ephemeral=True)


class WarnModal(discord.ui.Modal, title="Verwarnung"):
    grund = discord.ui.TextInput(label="Grund", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot, person: discord.Member):
        super().__init__()
        self.bot = bot
        self.person = person

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO warnings(user_id, reason, by_id, created_at) VALUES(?, ?, ?, ?)",
            (self.person.id, str(self.grund), interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["sanktionen"])
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} hat {self.person.mention} verwarnt: {self.grund}",
        )
        await interaction.response.send_message(f"Verwarnung für {self.person.mention}.", ephemeral=True)


class LagerModal(discord.ui.Modal):
    item = discord.ui.TextInput(label="Was (genau wie im Lager)", required=True, max_length=80)
    menge = discord.ui.TextInput(label="Wie viel (Zahl)", required=True, max_length=8)
    wer = discord.ui.TextInput(
        label="Wer (leer = du)",
        required=False,
        max_length=40,
    )

    def __init__(self, bot, direction: int):
        title = "Reinlegen" if direction > 0 else "Rausnehmen"
        super().__init__(title=title)
        self.bot = bot
        self.direction = direction

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.bot:
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
            text = str(self.wer).strip().lstrip("@")
            found = discord.utils.find(
                lambda m: m.name.lower() == text.lower() or m.display_name.lower() == text.lower(),
                interaction.guild.members,
            )
            who = found.id if found else interaction.user.id

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
        line = f"{interaction.user.mention}: {qty}× {item} {verb}. Neu: {new_qty}"
        await self.bot.log(interaction.guild, line, "Lager")
        logch = discord.utils.find(lambda c: "lager-log" in c.name.lower() or c.name.lower() == "lager-logs", interaction.guild.text_channels)
        if logch:
            try:
                await logch.send(line)
            except discord.HTTPException:
                pass
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
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
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
            "INSERT INTO vacations(user_id, start, end, reason, status, created_at) VALUES(?, ?, ?, ?, 'aktiv', ?)",
            (interaction.user.id, str(self.start), str(self.ende), str(self.grund), stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["urlaub"])
        await self.bot.log(
            interaction.guild,
            f"{interaction.user.mention} Urlaub {self.start} – {self.ende}: {self.grund}",
            "Urlaub",
        )
        await interaction.response.send_message("Urlaub eingetragen.", ephemeral=True)


class DienstView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Anmelden", style=discord.ButtonStyle.success, custom_id="dienst:an")
    async def anmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db.execute(
            """
            INSERT INTO attendance(user_id, status, reason, updated_at)
            VALUES(?, 'angemeldet', NULL, ?)
            ON CONFLICT(user_id) DO UPDATE SET status='angemeldet', reason=NULL, updated_at=excluded.updated_at
            """,
            (interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst", "aufstellung"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat sich angemeldet.")
        await interaction.response.send_message("Du bist jetzt **angemeldet**.", ephemeral=True)

    @discord.ui.button(label="Abmelden", style=discord.ButtonStyle.danger, custom_id="dienst:ab")
    async def abmelden(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.db.execute(
            """
            INSERT INTO attendance(user_id, status, reason, updated_at)
            VALUES(?, 'abgemeldet', '', ?)
            ON CONFLICT(user_id) DO UPDATE SET status='abgemeldet', reason='', updated_at=excluded.updated_at
            """,
            (interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst", "aufstellung"])
        await interaction.response.send_message("Du bist **abgemeldet**.", ephemeral=True)

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="dienst:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.bot.repost_panel(interaction.guild, "aufstellung")
        await interaction.followup.send("Aufstellung neu gesendet.", ephemeral=True)


class AbmeldungView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Wen abmelden?", custom_id="abm:who")
    async def abmelden(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        await interaction.response.send_modal(AbmeldenModal(self.bot, select.values[0]))

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Abmeldung löschen (nur Leitung)", custom_id="abm:delwho")
    async def loeschen(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leitung darf Abmeldungen löschen.", ephemeral=True)
        person = select.values[0]
        await self.bot.db.execute(
            "UPDATE attendance SET status='offen', reason=NULL, updated_at=? WHERE user_id=?",
            (stamp(), person.id),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["dienst", "aufstellung"])
        await interaction.response.send_message(f"Abmeldung von {person.mention} gelöscht.", ephemeral=True)

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="abm:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await lead_repost(interaction, self.bot, "dienst")


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
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(LagerNeuModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="lager:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await self.bot.refresh_panels(interaction.guild, ["lager"])
        await interaction.response.send_message("Lager aktualisiert.", ephemeral=True)


class SanktionView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Sanktion → Person wählen", custom_id="san:who")
    async def add(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(SanktionModal(self.bot, select.values[0]))

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Bezahlt → Person wählen", custom_id="san:paywho")
    async def pay(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        uid = select.values[0].id
        await self.bot.db.execute("UPDATE sanctions SET active = 0 WHERE user_id = ? AND active = 1", (uid,))
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["sanktionen"])
        await interaction.response.send_message(f"{select.values[0].mention} als bezahlt markiert.", ephemeral=True)

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="san:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await lead_repost(interaction, self.bot, "sanktionen")


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

    @discord.ui.button(label="Urlaub", style=discord.ButtonStyle.primary, custom_id="urlaub:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UrlaubModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="urlaub:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await lead_repost(interaction, self.bot, "urlaub")


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
        raw = interaction.user.display_name or interaction.user.name
        safe = "".join(c for c in raw if c.isalnum() or c in "-_ ")[:20].strip() or "user"
        ch = await interaction.guild.create_text_channel(
            name=f"🔫︱{safe}",
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

    @discord.ui.button(label="Check neu starten", style=discord.ButtonStyle.danger, custom_id="akt:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await self.bot.db.execute("DELETE FROM activity")
        await self.bot.db.commit()
        await interaction.response.defer(ephemeral=True)
        row = await __import__("database").get_panel(self.bot.db, f"{interaction.guild.id}:aktivitaet")
        if row and interaction.guild.get_channel(row["channel_id"]):
            await self.bot.repost_panel(interaction.guild, "aktivitaet")
        else:
            await self.bot.post_panel(interaction.channel, "aktivitaet")
        await self.bot.log(interaction.guild, f"{interaction.user.mention} hat den Aktivitätscheck neu gesendet.", "Aktivität")
        await interaction.followup.send("Neue Aktivitätscheck-Nachricht ist raus.", ephemeral=True)


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
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
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
        if not can_blacklist(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await self.bot.db.execute(
            "INSERT INTO blacklist(name, by_id, created_at) VALUES(?, ?, ?)",
            (str(self.name).strip(), interaction.user.id, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["blacklist"])
        await interaction.response.send_message(f"**{self.name}** steht auf der Blacklist.", ephemeral=True)


class BlacklistDelModal(discord.ui.Modal, title="Von Blacklist nehmen"):
    name = discord.ui.TextInput(label="Name genau wie in der Liste", required=True, max_length=80)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await self.bot.db.execute("DELETE FROM blacklist WHERE name = ?", (str(self.name).strip(),))
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["blacklist"])
        await interaction.response.send_message("Von der Blacklist genommen.", ephemeral=True)


class RangPickView(discord.ui.View):
    def __init__(self, bot, member: discord.Member):
        super().__init__(timeout=120)
        self.bot = bot
        self.member = member
        from ranks import RANK_ROLE_NAMES
        options = [discord.SelectOption(label=n, value=n) for n in RANK_ROLE_NAMES]
        sel = discord.ui.Select(placeholder="Rang anklicken", options=options)
        sel.callback = self.picked
        self.add_item(sel)

    async def picked(self, interaction: discord.Interaction):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        from ranks import RANK_ROLE_NAMES
        rname = interaction.data["values"][0]
        role = discord.utils.get(interaction.guild.roles, name=rname)
        if not role:
            return await interaction.response.send_message(f"Rolle `{rname}` fehlt auf dem Server.", ephemeral=True)
        try:
            to_remove = [r for r in self.member.roles if r.name in RANK_ROLE_NAMES and r != role]
            if to_remove:
                await self.member.remove_roles(*to_remove)
            await self.member.add_roles(role, reason=f"durch {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("Bot-Rolle zu weit unten.", ephemeral=True)
        await self.bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "dienst", "memberliste"])
        await self.bot.log(interaction.guild, f"{interaction.user.mention} gab {self.member.mention} **{rname}**")
        await interaction.response.send_message(f"{self.member.mention} → **{rname}**", ephemeral=True)


class RolleGebenModal(discord.ui.Modal, title="Rolle vergeben"):
    person_id = discord.ui.TextInput(label="Discord-ID", required=True, max_length=25)
    rang = discord.ui.TextInput(label="Rang-Name genau", required=True, max_length=80, placeholder="Rang 1 – Associate")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
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
    was = discord.ui.TextInput(label="Was + wie viel", style=discord.TextStyle.paragraph, required=True, max_length=800)

    def __init__(self, bot, who: discord.Member):
        super().__init__()
        self.bot = bot
        self.who = who

    async def on_submit(self, interaction: discord.Interaction):
        text = f"{self.who.mention} | {self.who.display_name}\n{self.was}"
        await self.bot.db.execute(
            "INSERT INTO lootdrops(body, created_at) VALUES(?, ?)",
            (text, stamp()),
        )
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["lootdrop"])
        await interaction.response.send_message("Lootdrop eingetragen.", ephemeral=True)


class RouteCheckModal(discord.ui.Modal, title="Routenkontrolle"):
    wer = discord.ui.TextInput(label="Wer", required=True, max_length=80)
    wieviele = discord.ui.TextInput(label="Wie viele", required=True, max_length=10)
    route = discord.ui.TextInput(label="Welche Route", required=True, max_length=80)
    typ = discord.ui.TextInput(label="Arbeiter oder Familie", required=True, max_length=40)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        body = f"Wer: {self.wer}\nWie viele: {self.wieviele}\nRoute: {self.route}\nTyp: {self.typ}"
        await self.bot.db.execute(
            "INSERT INTO routechecks(body, created_at) VALUES(?, ?)",
            (body, stamp()),
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
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(BlacklistModal(self.bot))

    @discord.ui.button(label="Rausnehmen", style=discord.ButtonStyle.secondary, custom_id="bl:del")
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
        await interaction.response.send_modal(BlacklistDelModal(self.bot))


class RoleConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        from ranks import RANK_ROLE_NAMES
        opts = [discord.SelectOption(label=n[:100], value=n) for n in RANK_ROLE_NAMES[:25]]
        sel = discord.ui.Select(placeholder="Rolle wählen", custom_id="role:reqpick", options=opts)
        sel.callback = self._picked
        self.add_item(sel)

    async def _picked(self, interaction: discord.Interaction):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        chosen = interaction.data["values"][0]
        e = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="Rollenanfrage")
        e.clear_fields()
        e.add_field(name="Gewählt", value=chosen, inline=False)
        await interaction.message.edit(embed=e)
        await interaction.response.send_message(f"**{chosen}** gewählt. Jetzt Bestätigen.", ephemeral=True)

    @discord.ui.button(label="Bestätigen", style=discord.ButtonStyle.success, custom_id="role:reqok")
    async def ok(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_high(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        if not interaction.message.embeds:
            return await interaction.response.send_message("Keine Anfrage.", ephemeral=True)
        e = interaction.message.embeds[0]
        uid = None
        if e.footer and e.footer.text and "UID:" in e.footer.text:
            try:
                uid = int(e.footer.text.split("UID:")[1].split()[0])
            except ValueError:
                uid = None
        chosen = None
        for f in e.fields:
            if f.name == "Gewählt":
                chosen = f.value
        if not uid or not chosen:
            return await interaction.response.send_message("Erst eine Rolle wählen.", ephemeral=True)
        member = interaction.guild.get_member(uid)
        role = discord.utils.get(interaction.guild.roles, name=chosen)
        if not member or not role:
            return await interaction.response.send_message("User oder Rolle nicht gefunden. Name muss exakt stimmen.", ephemeral=True)
        try:
            await member.add_roles(role, reason=f"Anfrage bestätigt von {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message("Bot darf die Rolle nicht geben (Reihenfolge).", ephemeral=True)
        await interaction.message.edit(
            content=f"# Rolle gegeben\n{member.mention} → **{chosen}** von {interaction.user.mention}",
            embed=None,
            view=None,
        )
        await interaction.response.send_message("Rolle vergeben.", ephemeral=True)


class RolleAnfrageView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Rolle anfragen", style=discord.ButtonStyle.primary, custom_id="role:ask")
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        ziel = discord.utils.find(
            lambda c: "rollen-anfrage-bestätigen" in c.name.lower()
            or ("rollen" in c.name.lower() and "bestätig" in c.name.lower()),
            interaction.guild.text_channels,
        )
        if not ziel:
            return await interaction.response.send_message(
                "Kanal `#rollen-anfrage-bestätigen` fehlt.", ephemeral=True
            )
        e = discord.Embed(title="Rollenanfrage", color=0x3B82C4)
        e.description = f"# {interaction.user.mention}\n**{interaction.user.display_name}** will eine Rolle."
        e.set_footer(text=f"UID:{interaction.user.id}")
        await ziel.send(content=f"# Rollenanfrage\n{interaction.user.mention}", embed=e, view=RoleConfirmView())
        await self.bot.log(interaction.guild, f"{interaction.user.mention} fragt eine Rolle an.", "Rollenanfrage")
        await interaction.response.send_message("Anfrage ist in `#rollen-anfrage-bestätigen`.", ephemeral=True)


class ClipAntragView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Kill-Clip beantragen", style=discord.ButtonStyle.primary, custom_id="clip:ask")
    async def ask(self, interaction: discord.Interaction, button: discord.ui.Button):
        from rules_data import CLIP_RULES
        cur = await self.bot.db.execute(
            "SELECT channel_id FROM clip_channels WHERE user_id = ?",
            (interaction.user.id,),
        )
        row = await cur.fetchone()
        if row and not is_high(interaction.user):
            ch = interaction.guild.get_channel(row["channel_id"])
            if ch:
                return await interaction.response.send_message(
                    f"Du hast schon einen Clip-Kanal: {ch.mention}", ephemeral=True
                )
            return await interaction.response.send_message("Nur 1 Clip-Kanal. Leadership darf mehrere.", ephemeral=True)
        cat = None
        for c in interaction.guild.categories:
            if c.name.lower() in {"kill-logs", "kill logs", "killlogs"}:
                cat = c
                break
        if cat is None:
            cat = await interaction.guild.create_category("Kill-Logs")
        raw = interaction.user.display_name or interaction.user.name
        safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_ ")[:20].strip() or "user"
        channel = await interaction.guild.create_text_channel(name=f"🔫︱{safe}", category=cat)
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

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Wer hat abgegeben?", custom_id="loot:who")
    async def who(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        user = select.values[0]
        await interaction.response.send_modal(LootModal(self.bot, user))


class RouteCheckView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Kontrolle eintragen", style=discord.ButtonStyle.primary, custom_id="rc:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RouteCheckModal(self.bot))


class AbgabeModal(discord.ui.Modal, title="Abgabe"):
    was = discord.ui.TextInput(label="Was", required=True, max_length=80)
    wieviel = discord.ui.TextInput(label="Wie viel", required=True, max_length=20)

    def __init__(self, bot, who: discord.Member):
        super().__init__()
        self.bot = bot
        self.who = who

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        text = f"{self.who.mention} | {self.who.display_name}\n{self.was} × {self.wieviel}"
        await self.bot.db.execute(
            "INSERT INTO abgaben(body, created_at) VALUES(?, ?)",
            (text, stamp()),
        )
        await self.bot.db.commit()
        e = discord.Embed(title="Abgabe", color=0x3B82C4)
        e.description = f"**Wer:** {self.who.mention}\n**Was:** {self.was}\n**Wie viel:** {self.wieviel}"
        e.set_footer(text=stamp())
        await interaction.channel.send(embed=e)
        await interaction.response.send_message("Abgabe gepostet.", ephemeral=True)


class AbgabeView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Wer gibt ab?", custom_id="abg:who")
    async def who(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(AbgabeModal(self.bot, select.values[0]))


class KasseModal(discord.ui.Modal, title="Fraktionskasse"):
    amount = discord.ui.TextInput(label="Neuer Bestand", required=True, max_length=40)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        import database as dbmod
        await dbmod.set_setting(self.bot.db, "frak_kasse", str(self.amount).strip())
        await self.bot.refresh_panels(interaction.guild, ["kasse"])
        await interaction.response.send_message("Kasse aktualisiert.", ephemeral=True)


class KasseView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Bestand setzen", style=discord.ButtonStyle.primary, custom_id="kasse:set")
    async def set_amt(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(KasseModal(self.bot))


class RouteModal(discord.ui.Modal, title="Route eintragen"):
    name = discord.ui.TextInput(label="Welche Route", required=True, max_length=80)
    menge = discord.ui.TextInput(label="Menge / Abgabe", required=True, max_length=40)
    bis = discord.ui.TextInput(label="Abgeben bis wann", required=True, max_length=40)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        try:
            await self.bot.db.execute(
                "INSERT INTO routes(name, amount) VALUES(?, ?)",
                (str(self.name).strip(), f"{self.menge} | bis {self.bis}"),
            )
        except Exception:
            await self.bot.db.execute("INSERT INTO routes(name) VALUES(?)", (f"{self.name} — {self.menge}",))
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["routen"])
        await interaction.response.send_message(f"Route **{self.name}** ({self.menge}) steht in der Liste.", ephemeral=True)


class RouteDelModal(discord.ui.Modal, title="Route löschen"):
    name = discord.ui.TextInput(label="Route genau wie in der Liste", required=True, max_length=80)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await self.bot.db.execute("DELETE FROM routes WHERE name = ?", (str(self.name).strip(),))
        await self.bot.db.commit()
        await self.bot.refresh_panels(interaction.guild, ["routen"])
        await interaction.response.send_message("Route gelöscht.", ephemeral=True)


class EinkaufModal(discord.ui.Modal, title="Eingekauft"):
    titel = discord.ui.TextInput(label="Titel", required=True, max_length=80)
    zeit = discord.ui.TextInput(label="Einkauf von–bis", required=True, max_length=80)
    pflicht = discord.ui.TextInput(label="Pflicht Abgabe", required=True, max_length=150)
    extra = discord.ui.TextInput(label="Ablauf / Preise / Rest", style=discord.TextStyle.paragraph, required=True, max_length=800)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        body = f"**{self.titel}**\nEinkauf: {self.zeit}\nPflicht: {self.pflicht}\n{self.extra}"
        await self.bot.db.execute("INSERT INTO einkauf(body) VALUES(?)", (body,))
        await self.bot.db.commit()
        e = discord.Embed(title=str(self.titel), color=0x3B82C4)
        e.description = f"**Erneuter Einkauf:**\n{self.zeit}\n\n**Pflicht Abgabe:**\n{self.pflicht}\n\n{self.extra}"
        e.set_footer(text=stamp())
        from panels import ping_ophelia
        await interaction.channel.send(content=ping_ophelia(interaction.guild), embed=e)
        await self.bot.refresh_panels(interaction.guild, ["einkauf"])
        await interaction.response.send_message("Eingekauft gepostet.", ephemeral=True)


class EinkaufView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Eingekauft eintragen", style=discord.ButtonStyle.primary, custom_id="ek:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_route(interaction.user):
            return await interaction.response.send_message("Nur Leadership oder Rang 9.", ephemeral=True)
        await interaction.response.send_modal(EinkaufModal(self.bot))


class RouteView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Route eintragen", style=discord.ButtonStyle.primary, custom_id="route:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_route(interaction.user):
            return await interaction.response.send_message("Nur Leadership oder Rang 9.", ephemeral=True)
        await interaction.response.send_modal(RouteModal(self.bot))

    @discord.ui.button(label="Aktualisieren", style=discord.ButtonStyle.secondary, custom_id="route:ref")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await lead_repost(interaction, self.bot, "routen")

    @discord.ui.button(label="Löschen", style=discord.ButtonStyle.danger, custom_id="route:del")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_leader(interaction.user):
            return await interaction.response.send_message("Nur Leadership kann das ausführen.", ephemeral=True)
        await interaction.response.send_modal(RouteDelModal(self.bot))


class ArbeiterModal(discord.ui.Modal, title="Arbeiter eintragen"):
    name = discord.ui.TextInput(label="Name", required=True, max_length=80)
    telefon = discord.ui.TextInput(label="Telefonnummer", required=True, max_length=40)
    von = discord.ui.TextInput(label="Von wem", required=True, max_length=80)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Jetzt in **diesen Kanal das Bild** schicken (Datei vom PC). 10 Minuten Zeit.",
            ephemeral=True,
        )

        def check(msg: discord.Message):
            return (
                msg.author.id == interaction.user.id
                and msg.channel.id == interaction.channel.id
                and msg.attachments
            )

        file = None
        try:
            msg = await self.bot.wait_for("message", timeout=600, check=check)
            att = msg.attachments[0]
            file = await att.to_file()
            try:
                await msg.delete()
            except discord.HTTPException:
                pass
        except Exception:
            file = None
        e = discord.Embed(title="Arbeiter", color=0x3B82C4)
        e.description = f"**Name:** {self.name}\n**Telefon:** {self.telefon}\n**Von:** {self.von}"
        e.set_footer(text=stamp())
        kwargs = {"embed": e}
        if file:
            kwargs["file"] = file
        await interaction.channel.send(**kwargs)


class ArbeiterDelModal(discord.ui.Modal, title="Arbeiter rausnehmen"):
    name = discord.ui.TextInput(label="Name genau", required=True, max_length=80)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.channel.send(f"**Arbeiter raus:** {self.name} (von {interaction.user.mention})")
        await interaction.response.send_message("Rausgenommen (Nachricht gepostet).", ephemeral=True)


class ArbeiterView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Arbeiter eintragen", style=discord.ButtonStyle.primary, custom_id="arb:add")
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ArbeiterModal(self.bot))

    @discord.ui.button(label="Arbeiter rausnehmen", style=discord.ButtonStyle.danger, custom_id="arb:del")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ArbeiterDelModal(self.bot))
