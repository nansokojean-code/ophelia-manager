BUILD_ID = "2026-09-09-setup-custom-panel-v5-hard-alias"
import asyncio
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Berlin")
except Exception:
    TZ = None
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

import database
import panels
import views
from ranks import is_high, is_leader, is_officer, rank_names, set_areas, set_guild_roles


intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.guilds = True
intents.message_content = True

SETUP_PANELS = [
    "aufstellung",
    "dienst",
    "aktivitaet",
    "katalog",
    "sanktionen",
    "blacklist",
    "rang",
    "memberliste",
    "mitarbeiter",
    "pflicht",
    "lager",
    "bosslager",
    "lootdrop",
    "abgaben",
    "kasse",
    "routen",
    "einkauf",
    "routecheck",
    "arbeiter",
    "urlaub",
    "rollenanfrage",
    "rollenbestaetigen",
    "clipantrag",
    "tickets",
]

PANEL_NAMES = [
    "mitarbeiter",
    "memberliste",
    "rang",
    "aufstellung",
    "dienst",
    "katalog",
    "sanktionen",
    "ausruestung",
    "lager",
    "bosslager",
    "urlaub",
    "infos",
    "arbeiter",
    "tickets",
    "regeln",
    "status",
    "aktivitaet",
    "notizen",
    "blacklist",
    "pflicht",
    "routen",
    "einkauf",
    "routecheck",
    "lootdrop",
    "rollenanfrage",
    "clipantrag",
    "abgaben",
    "kasse",
]


class ClubBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.db = None

    async def setup_hook(self):
        self.db = await database.connect()
        self.add_view(views.DienstView(self))
        self.add_view(views.AufstellungView(self))
        self.add_view(views.LagerView(self))
        self.add_view(views.BossLagerView(self))
        self.add_view(views.SanktionView(self))
        self.add_view(views.AusruestungView(self))
        self.add_view(views.UrlaubView(self))
        self.add_view(views.RangView(self))
        self.add_view(views.TicketView(self))
        self.add_view(views.AktivitaetView(self))
        self.add_view(views.StatusView(self))
        self.add_view(views.BlacklistView(self))
        self.add_view(views.RolleAnfrageView(self))
        self.add_view(views.RoleConfirmView())
        self.add_view(views.RolleBestaetigenPanelView(self))
        self.add_view(views.ClipAntragView(self))
        self.add_view(views.LootView(self))
        self.add_view(views.RouteCheckView(self))
        self.add_view(views.AbmeldungView(self))
        self.add_view(views.AbgabeView(self))
        self.add_view(views.KasseView(self))
        self.add_view(views.SanktionPayView())
        self.add_view(views.RouteView(self))
        self.add_view(views.EinkaufView(self))
        self.add_view(views.ArbeiterView(self))
        try:
            await self.tree.sync()
        except Exception as exc:
            print("Command-Sync:", exc)

    async def log(self, guild: discord.Guild, text: str, kategorie="Allgemein"):
        raw = await database.get_setting(self.db, f"log_channel:{guild.id}")
        ch = guild.get_channel(int(raw)) if raw else None
        if not ch:
            ch = discord.utils.find(lambda c: "log" in c.name.lower(), guild.text_channels)
        if not ch:
            return
        e = discord.Embed(title=kategorie, description=text, color=0x3B82C4)
        thread = None
        try:
            for t in getattr(ch, "threads", []):
                if t.name.lower() == str(kategorie).lower():
                    thread = t
                    break
            if thread is None:
                starter = await ch.send(f"**Kategorie: {kategorie}**")
                thread = await starter.create_thread(name=str(kategorie)[:90])
        except discord.HTTPException:
            thread = None
        try:
            await (thread or ch).send(embed=e)
        except discord.HTTPException:
            pass

    async def refresh_panels(self, guild: discord.Guild, names=None):
        # Builder werden absichtlich lazy erzeugt. In älteren Versionen wurden hier
        # für *alle* Panels Coroutine-Objekte erstellt, obwohl nur ein Panel
        # aktualisiert wurde. Das erzeugte unawaited-coroutine Warnungen und machte
        # Panel-Updates unnötig instabil.
        mapping = {
            "mitarbeiter": ("mitarbeiter", lambda: panels.embed_mitarbeiter(guild), lambda: None),
            "memberliste": ("memberliste", lambda: panels.embed_memberliste(guild), lambda: None),
            "rang": ("rang", lambda: panels.embed_rangsystem(guild), lambda: None),
            "aufstellung": ("aufstellung", lambda: panels.embed_aufstellung(guild, self.db), lambda: views.DienstView(self)),
            "dienst": ("dienst", lambda: panels.embed_abmeldung(guild, self.db), lambda: views.AbmeldungView(self)),
            "katalog": ("katalog", lambda: panels.embed_katalog(self.db), lambda: None),
            "sanktionen": ("sanktionen", lambda: panels.embed_sanktionen(guild, self.db), lambda: views.SanktionView(self)),
            "ausruestung": ("ausruestung", lambda: panels.embed_ausruestung(guild, self.db), lambda: views.AusruestungView(self)),
            "lager": ("lager", lambda: panels.embed_lager(self.db), lambda: views.LagerView(self)),
            "bosslager": ("bosslager", lambda: panels.embed_boss_lager(self.db), lambda: views.BossLagerView(self)),
            "urlaub": ("urlaub", lambda: panels.embed_urlaub(guild, self.db), lambda: views.UrlaubView(self)),
            "infos": ("infos", lambda: panels.embed_infos(self.db), lambda: None),
            "arbeiter": ("arbeiter", lambda: panels.embed_arbeiter(guild, self.db), lambda: views.ArbeiterView(self)),
            "tickets": ("tickets", lambda: panels.embed_tickets(), lambda: views.TicketView(self)),
            "regeln": ("regeln", lambda: panels.embed_regeln(self.db), lambda: None),
            "status": ("status", lambda: panels.embed_status(self.db), lambda: views.StatusView(self)),
            "aktivitaet": ("aktivitaet", lambda: panels.embed_aktivitaet(guild, self.db), lambda: views.AktivitaetView(self)),
            "notizen": ("notizen", lambda: panels.embed_notizen(self.db), lambda: None),
            "blacklist": ("blacklist", lambda: panels.embed_blacklist(self.db), lambda: views.BlacklistView(self)),
            "pflicht": ("pflicht", lambda: panels.embed_pflicht(), lambda: None),
            "routen": ("routen", lambda: panels.embed_routes(self.db), lambda: views.RouteView(self)),
            "einkauf": ("einkauf", lambda: panels.embed_einkauf(self.db), lambda: views.EinkaufView(self)),
            "routecheck": ("routecheck", lambda: panels.embed_routecheck(self.db), lambda: views.RouteCheckView(self)),
            "lootdrop": ("lootdrop", lambda: panels.embed_lootdrop(self.db), lambda: views.LootView(self)),
            "rollenanfrage": ("rollenanfrage", lambda: panels.embed_rollenanfrage(), lambda: views.RolleAnfrageView(self)),
            "rollenbestaetigen": ("rollenbestaetigen", lambda: panels.embed_rollenbestaetigen(), lambda: None),
            "clipantrag": ("clipantrag", lambda: panels.embed_clipantrag(), lambda: views.ClipAntragView(self)),
            "abgaben": ("abgaben", lambda: panels.embed_abgaben(self.db), lambda: views.AbgabeView(self)),
            "kasse": ("kasse", lambda: panels.embed_kasse(self.db), lambda: views.KasseView(self)),
        }
        targets = names or list(mapping.keys())
        updated = 0
        for name in targets:
            if name == "aktivitaet" or name not in mapping:
                continue
            key, embed_factory, view_factory = mapping[name]
            row = await database.get_panel(self.db, f"{guild.id}:{key}")
            if not row:
                continue
            ch = guild.get_channel(row["channel_id"])
            if not ch:
                continue
            try:
                msg = await ch.fetch_message(row["message_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
            view = view_factory()
            if name == "routen":
                try:
                    await msg.edit(content="# Unsere Route", embed=None, view=view)
                    updated += 1
                except discord.HTTPException:
                    pass
                continue
            try:
                embed = await embed_factory()
                await msg.edit(embed=embed, view=view)
                updated += 1
            except discord.HTTPException:
                pass
        return updated

    async def post_panel(self, channel: discord.TextChannel, key: str):
        guild = channel.guild

        # Legacy-/Cache-Schutz: Discord kann nach alten Deploys noch frühere
        # Choice-Werte wie "Custom-Panel" senden. Hier wird deshalb direkt
        # an der zentralen Panel-Funktion normalisiert, damit selbst alte
        # Slash-Command-Payloads nicht mehr in einen "nicht gefunden"-Fehler laufen.
        raw_key = str(key or "").strip()
        normalized_key = raw_key.lower().replace("_", "-").replace(" ", "-")
        legacy_aliases = {
            "custom-panel": "bosslager",
            "custompanel": "bosslager",
            "boss-menü-lager": "bosslager",
            "boss-menu-lager": "bosslager",
            "boss-menue-lager": "bosslager",
            "boss-manager": "bosslager",
            "bossmanager": "bosslager",
            "unsere-route": "routen",
            "route": "routen",
        }
        key = legacy_aliases.get(normalized_key, normalized_key.replace("-", ""))

        builders = {
            "mitarbeiter": (lambda: panels.embed_mitarbeiter(guild), lambda: None),
            "memberliste": (lambda: panels.embed_memberliste(guild), lambda: None),
            "rang": (lambda: panels.embed_rangsystem(guild), lambda: None),
            "aufstellung": (lambda: panels.embed_aufstellung(guild, self.db), lambda: views.DienstView(self)),
            "dienst": (lambda: panels.embed_abmeldung(guild, self.db), lambda: views.AbmeldungView(self)),
            "katalog": (lambda: panels.embed_katalog(self.db), lambda: None),
            "sanktionen": (lambda: panels.embed_sanktionen(guild, self.db), lambda: views.SanktionView(self)),
            "ausruestung": (lambda: panels.embed_ausruestung(guild, self.db), lambda: views.AusruestungView(self)),
            "lager": (lambda: panels.embed_lager(self.db), lambda: views.LagerView(self)),
            "bosslager": (lambda: panels.embed_boss_lager(self.db), lambda: views.BossLagerView(self)),
            "urlaub": (lambda: panels.embed_urlaub(guild, self.db), lambda: views.UrlaubView(self)),
            "infos": (lambda: panels.embed_infos(self.db), lambda: None),
            "arbeiter": (lambda: panels.embed_arbeiter(guild, self.db), lambda: views.ArbeiterView(self)),
            "tickets": (lambda: panels.embed_tickets(), lambda: views.TicketView(self)),
            "regeln": (lambda: panels.embed_regeln(self.db), lambda: None),
            "status": (lambda: panels.embed_status(self.db), lambda: views.StatusView(self)),
            "aktivitaet": (lambda: panels.embed_aktivitaet(guild, self.db), lambda: views.AktivitaetView(self)),
            "notizen": (lambda: panels.embed_notizen(self.db), lambda: None),
            "blacklist": (lambda: panels.embed_blacklist(self.db), lambda: views.BlacklistView(self)),
            "pflicht": (lambda: panels.embed_pflicht(), lambda: None),
            "routen": (lambda: panels.embed_routes(self.db), lambda: views.RouteView(self)),
            "einkauf": (lambda: panels.embed_einkauf(self.db), lambda: views.EinkaufView(self)),
            "routecheck": (lambda: panels.embed_routecheck(self.db), lambda: views.RouteCheckView(self)),
            "lootdrop": (lambda: panels.embed_lootdrop(self.db), lambda: views.LootView(self)),
            "rollenanfrage": (lambda: panels.embed_rollenanfrage(), lambda: views.RolleAnfrageView(self)),
            "rollenbestaetigen": (lambda: panels.embed_rollenbestaetigen(), lambda: None),
            "clipantrag": (lambda: panels.embed_clipantrag(), lambda: views.ClipAntragView(self)),
            "abgaben": (lambda: panels.embed_abgaben(self.db), lambda: views.AbgabeView(self)),
            "kasse": (lambda: panels.embed_kasse(self.db), lambda: views.KasseView(self)),
        }
        if key not in builders:
            raise KeyError(f"Unbekanntes Panel: {key}")
        embed_factory, view_factory = builders[key]
        view = view_factory()
        if key == "aktivitaet":
            ping = panels.ping_ophelia(guild)
            img = Path(__file__).resolve().parent.parent / "assets" / "aktivitaet.png"
            kwargs = {"content": ping, "view": view}
            if img.exists():
                kwargs["file"] = discord.File(img, filename="aktivitaet.png")
            msg = await channel.send(**kwargs)
        elif key == "routen":
            msg = await channel.send(content="# Unsere Route", view=view)
        else:
            embed = await embed_factory()
            heading = embed.title or key
            msg = await channel.send(content=f"# {heading}", embed=embed, view=view)
        await database.set_panel(self.db, f"{guild.id}:{key}", channel.id, msg.id)
        return msg

    async def repost_panel(self, guild, key):
        row = await database.get_panel(self.db, f"{guild.id}:{key}")
        if not row:
            return None
        ch = guild.get_channel(row["channel_id"])
        if not ch:
            return None
        old = None
        try:
            old = await ch.fetch_message(row["message_id"])
        except discord.HTTPException:
            old = None
        # Erst neue Nachricht posten und DB-Zeiger aktualisieren. So bleibt bei einem
        # Discord-Fehler nicht plötzlich gar kein Panel mehr übrig.
        msg = await self.post_panel(ch, key)
        if old and old.id != msg.id:
            try:
                await old.delete()
            except discord.HTTPException:
                pass
        return msg


bot = ClubBot()


@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Ophelia Manager")
    )
    print(f"Ophelia Manager online als {bot.user} ({bot.user.id})")
    print(f"Build: {BUILD_ID}")

    # Slash-Commands pro Server synchronisieren, damit Discord die festen
    # /setup-Panel-Optionen sofort und zuverlässig aktualisiert.
    # Die eigentlichen Commands/Funktionen bleiben unverändert.
    for g in bot.guilds:
        try:
            # Alte/stale Server-Commands (z. B. ein früheres „Custom-Panel“)
            # zuerst vollständig aus dem lokalen Tree entfernen und danach
            # die aktuellen globalen Commands frisch pro Server registrieren.
            bot.tree.clear_commands(guild=g)
            bot.tree.copy_global_to(guild=g)
            synced = await bot.tree.sync(guild=g)
            print(f"Command-Sync für {g.name}: {len(synced)} Commands")
        except Exception as exc:
            print(f"Command-Sync für {g.name} fehlgeschlagen:", exc)

    for g in bot.guilds:
        raw = await database.get_setting(bot.db, f"ranks:{g.id}")
        lead = await database.get_setting(bot.db, f"leaders:{g.id}")
        off = await database.get_setting(bot.db, f"officers:{g.id}")
        web_ranks = await database.get_setting(bot.db, "web_ranks")
        web_lead = await database.get_setting(bot.db, "web_leaders")
        web_off = await database.get_setting(bot.db, "web_officers")
        web_areas = await database.get_setting(bot.db, "web_areas")
        if web_areas:
            set_areas([x.strip() for x in web_areas.splitlines() if x.strip()])
        if web_ranks:
            raw = "|".join(x.strip() for x in web_ranks.splitlines() if x.strip())
            lead = "|".join(x.strip() for x in (web_lead or "").splitlines() if x.strip()) or lead
            off = "|".join(x.strip() for x in (web_off or "").splitlines() if x.strip()) or off
        if raw:
            set_guild_roles(
                g.id,
                raw.split("|"),
                (lead.split("|") if lead else None),
                (off.split("|") if off else None),
            )
        try:
            await bot.refresh_panels(g)
        except Exception as e:
            print("Refresh error", g.id, e)
    if not daily_clock.is_running():
        daily_clock.start()


@tasks.loop(minutes=1)
async def daily_clock():
    now = datetime.now(TZ) if TZ else datetime.now()
    mark = now.strftime("%Y-%m-%d-%H-%M")
    last = await database.get_setting(bot.db, "clock_tick")
    if last == mark:
        return
    await database.set_setting(bot.db, "clock_tick", mark)
    if now.hour == 0 and now.minute == 0:
        for g in bot.guilds:
            await bot.db.execute("DELETE FROM attendance")
            await bot.db.commit()
            await bot.repost_panel(g, "aufstellung")
            await bot.log(g, "00:00 neue Aufstellung.", "Aufstellung")
        last_akt = await database.get_setting(bot.db, "last_aktivitaet_date", "")
        day = now.strftime("%Y-%m-%d")
        if last_akt:
            from datetime import date as _date
            try:
                prev = _date.fromisoformat(last_akt)
                delta = (_date.fromisoformat(day) - prev).days
            except ValueError:
                delta = 99
        else:
            delta = 99
        if delta >= 4:
            for g in bot.guilds:
                await bot.repost_panel(g, "aktivitaet")
            await database.set_setting(bot.db, "last_aktivitaet_date", day)
    if now.hour == 18 and now.minute == 0:
        from panels import staff_members
        for g in bot.guilds:
            cur = await bot.db.execute("SELECT user_id, status FROM attendance")
            rows = {r["user_id"]: r["status"] for r in await cur.fetchall()}
            cur = await bot.db.execute(
                "SELECT user_id FROM vacations WHERE status IN ('genehmigt', 'aktiv')"
            )
            vac = {r["user_id"] for r in await cur.fetchall()}
            hit = []
            for m in staff_members(g):
                if m.id in vac:
                    continue
                st = rows.get(m.id, "offen")
                if st in {"angemeldet", "abgemeldet"}:
                    continue
                hit.append(m)
                await bot.db.execute(
                    """
                    INSERT INTO sanctions(user_id, kind, reason, until_text, by_id, active, created_at)
                    VALUES(?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        m.id,
                        "Nicht an-/abgemeldet (offen nach 18 Uhr)",
                        "15k",
                        "bis morgen 19 Uhr",
                        bot.user.id,
                        now.strftime("%d.%m.%Y %H:%M"),
                    ),
                )
            await bot.db.commit()
            if hit:
                await bot.refresh_panels(g, ["sanktionen", "aufstellung", "dienst"])
                await bot.log(
                    g,
                    "18:00 Offen → 15k Sanktion: " + ", ".join(m.mention for m in hit[:30]),
                    "Sanktionen",
                )
                prow = await database.get_panel(bot.db, f"{g.id}:sanktionen")
                sch = (
                    g.get_channel(prow["channel_id"])
                    if prow
                    else discord.utils.find(
                        lambda c: "sanktion" in c.name.lower() and "katalog" not in c.name.lower(),
                        g.text_channels,
                    )
                )
                if sch:
                    for m in hit:
                        cur = await bot.db.execute(
                            "SELECT id FROM sanctions WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                            (m.id,),
                        )
                        row = await cur.fetchone()
                        sid = row["id"] if row else "?"
                        e = discord.Embed(title="Sanktion", color=0xC0392B)
                        e.description = (
                            f"**Wer:** {m.mention}\n"
                            f"**Was:** Nicht an-/abgemeldet (offen nach 18 Uhr)\n"
                            f"**Wie viel:** 15k\n"
                            f"**Bis:** bis morgen 19 Uhr"
                        )
                        e.set_footer(text=f"SID:{sid}")
                        await sch.send(embed=e, view=views.SanktionPayView())


@daily_clock.before_loop
async def _clock_wait():
    await bot.wait_until_ready()


async def _named_channel(guild, key):
    raw = await database.get_setting(bot.db, f"{key}:{guild.id}")
    if raw:
        try:
            ch = guild.get_channel(int(raw))
            if ch:
                return ch
        except (TypeError, ValueError):
            pass
    aliases = {
        "bloodin_channel": ("blood-in", "bloodin", "blood in"),
        "bloodout_channel": ("bloodout", "blood-out", "blood out"),
        "log_channel": ("log-kanal", "logs", "log"),
    }
    names = aliases.get(key, ())
    for c in guild.text_channels:
        n = c.name.lower().replace("💧", "").replace("|", " ")
        if any(a in n for a in names):
            return c
    return None


async def _delete_clip(guild, user_id):
    cur = await bot.db.execute("SELECT channel_id FROM clip_channels WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    if not row:
        return
    ch = guild.get_channel(row["channel_id"])
    if ch:
        try:
            await ch.delete(reason="Blood-Out")
        except discord.HTTPException:
            pass
    await bot.db.execute("DELETE FROM clip_channels WHERE user_id = ?", (user_id,))
    await bot.db.commit()


@bot.event
async def on_member_join(member: discord.Member):
    await bot.refresh_panels(member.guild, ["memberliste", "mitarbeiter", "dienst"])
    msg = f"Das ist dein Blood-In {member.mention} – Willkommen bei Ophelia"
    ch = await _named_channel(member.guild, "bloodin_channel")
    if ch:
        await ch.send(msg)
    await bot.log(member.guild, msg, "Blood-In")


@bot.event
async def on_member_remove(member: discord.Member):
    await _delete_clip(member.guild, member.id)
    await bot.refresh_panels(member.guild, ["memberliste", "mitarbeiter", "dienst", "aufstellung", "rang"])
    msg = f"Das ist dein Blood-Out **{member}**"
    ch = await _named_channel(member.guild, "bloodout_channel")
    if ch:
        await ch.send(msg)
    await bot.log(member.guild, f"{msg} (Kanal: {ch.mention if ch else 'kein Blood-Out-Kanal gesetzt'})", "Blood-Out")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles or before.nick != after.nick or before.display_name != after.display_name:
        await bot.refresh_panels(
            after.guild,
            ["memberliste", "mitarbeiter", "rang", "dienst", "aufstellung", "ausruestung", "arbeiter"],
        )


@bot.tree.command(name="setup", description="Eine Live-Liste in diesen Kanal setzen")
@app_commands.describe(panel="Welche Liste soll hier stehen?")
@app_commands.choices(panel=[app_commands.Choice(name=n, value=n) for n in SETUP_PANELS])
async def setup_cmd(interaction: discord.Interaction, panel: str):
    if not is_leader(interaction.user):
        if interaction.response.is_done():
            return await interaction.followup.send("Nur Leitung.", ephemeral=True)
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)

    # Discord kann nach alten Deploys noch einen veralteten Choice-Wert senden.
    # Deshalb niemals direkt mit dem Payload in post_panel gehen.
    raw = str(panel or "").strip()
    normalized = raw.lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "custom-panel": "bosslager",
        "custompanel": "bosslager",
        "boss-menü-lager": "bosslager",
        "boss-menu-lager": "bosslager",
        "bosslager": "bosslager",
        "boss-menue-lager": "bosslager",
        "boss-manager": "bosslager",
        "bossmanager": "bosslager",
        "unsere-route": "routen",
        "route": "routen",
    }
    key = aliases.get(normalized, normalized.replace("-", ""))

    # Exakte aktuelle Werte bevorzugen.
    if raw.lower() in SETUP_PANELS:
        key = raw.lower()
    elif normalized in SETUP_PANELS:
        key = normalized

    if key not in SETUP_PANELS:
        text = ", ".join(f"`{x}`" for x in SETUP_PANELS)
        msg = (
            f"Die alte Panel-Option **{raw or 'unbekannt'}** ist nicht mehr gültig. "
            f"Öffne `/setup` bitte neu und wähle eines der aktuellen Panels:\n{text}"
        )
        if interaction.response.is_done():
            return await interaction.followup.send(msg, ephemeral=True)
        return await interaction.response.send_message(msg, ephemeral=True)

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await bot.post_panel(interaction.channel, key)
        await interaction.followup.send(
            f"Ophelia Manager hat **{key}** hier gepostet. Die Liste bleibt aktuell.",
            ephemeral=True,
        )
    except (discord.NotFound, discord.InteractionResponded):
        # Das Panel selbst wurde ggf. bereits gepostet; alte/abgelaufene Interaction
        # soll nicht als sichtbarer Fehler im Discord landen.
        return
    except KeyError:
        # Zusätzliche Absicherung gegen alte Slash-Command-Payloads.
        await interaction.followup.send(
            "Diese alte Panel-Auswahl existiert nicht mehr. Bitte `/setup` neu öffnen.",
            ephemeral=True,
        )


@bot.tree.command(name="version", description="Zeigt die aktuell laufende Bot-Version")
async def version_cmd(interaction: discord.Interaction):
    msg = f"Ophelia Manager Build: `{BUILD_ID}`"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="anmelden", description="Bei der Aufstellung anmelden")
async def cmd_anmelden(interaction: discord.Interaction):
    acknowledged = await views.safe_defer(interaction)
    await views.set_dienst(bot, interaction.user, "angemeldet")
    await views.safe_feedback(interaction, "Angemeldet.", acknowledged)


@bot.tree.command(name="abmelden", description="Bei der Aufstellung abmelden")
async def cmd_abmelden(interaction: discord.Interaction):
    acknowledged = await views.safe_defer(interaction)
    await views.set_dienst(bot, interaction.user, "abgemeldet")
    await views.safe_feedback(interaction, "Abgemeldet.", acknowledged)


@bot.tree.command(name="logkanal", description="Log-Kanal festlegen")
async def logkanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await database.set_setting(bot.db, f"log_channel:{interaction.guild.id}", str(kanal.id))
    await interaction.response.send_message(f"Log-Kanal ist jetzt {kanal.mention}.", ephemeral=True)


@bot.tree.command(name="bloodin_kanal", description="Kanal für Blood-In Willkommen")
async def bloodin_kanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leadership.", ephemeral=True)
    await database.set_setting(bot.db, f"bloodin_channel:{interaction.guild.id}", str(kanal.id))
    await interaction.response.send_message(f"Blood-In Kanal: {kanal.mention}", ephemeral=True)


@bot.tree.command(name="bloodout_kanal", description="Kanal für Blood-Out")
async def bloodout_kanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leadership.", ephemeral=True)
    await database.set_setting(bot.db, f"bloodout_channel:{interaction.guild.id}", str(kanal.id))
    await interaction.response.send_message(f"Blood-Out Kanal: {kanal.mention}", ephemeral=True)


@bot.tree.command(name="kick", description="Blood-Out + Kick + Clip-Kanal löschen")
async def kick_cmd(interaction: discord.Interaction, person: discord.Member):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Rang 12–9.", ephemeral=True)
    await _delete_clip(interaction.guild, person.id)
    ch = await _named_channel(interaction.guild, "bloodout_channel")
    text = f"Das ist dein Blood-Out {person.mention}"
    if ch:
        await ch.send(text)
    await bot.log(interaction.guild, text, "Blood-Out")
    try:
        await person.kick(reason=f"Blood-Out durch {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message("Kick nicht erlaubt (Rechte/Rolle).", ephemeral=True)
    await interaction.response.send_message(f"{person} wurde gekickt (Blood-Out).", ephemeral=True)


@bot.tree.command(name="rangrollen", description="Eure echten Discord-Rollen festlegen (oben nach unten)")
@app_commands.describe(
    rang1="Höchster Rang",
    rang2="2. Rang",
    rang3="3. Rang",
    rang4="4. Rang",
    rang5="5. Rang",
    rang6="6. Rang",
    rang7="7. Rang",
    rang8="8. Rang",
    leitung="Welche Rolle darf alles? (sonst = rang1)",
    team="Welche Rolle darf Sanktionen/Aufstellung? (sonst = rang1+rang2)",
)
async def rangrollen(
    interaction: discord.Interaction,
    rang1: discord.Role,
    rang2: discord.Role = None,
    rang3: discord.Role = None,
    rang4: discord.Role = None,
    rang5: discord.Role = None,
    rang6: discord.Role = None,
    rang7: discord.Role = None,
    rang8: discord.Role = None,
    leitung: discord.Role = None,
    team: discord.Role = None,
):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung / Admin.", ephemeral=True)
    ranks = [r.name for r in (rang1, rang2, rang3, rang4, rang5, rang6, rang7, rang8) if r]
    leaders = [leitung.name] if leitung else [ranks[0]]
    officers = [team.name] if team else ranks[:2]
    set_guild_roles(interaction.guild.id, ranks, leaders, officers)
    await database.set_setting(bot.db, f"ranks:{interaction.guild.id}", "|".join(ranks))
    await database.set_setting(bot.db, f"leaders:{interaction.guild.id}", "|".join(leaders))
    await database.set_setting(bot.db, f"officers:{interaction.guild.id}", "|".join(officers))
    await bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "memberliste", "dienst"])
    await interaction.response.send_message(
        "Rang-Rollen gespeichert:\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(ranks)),
        ephemeral=True,
    )


@bot.tree.command(name="befoerdern", description="Person auf eine Rang-Rolle setzen")
async def befoerdern(interaction: discord.Interaction, person: discord.Member, rolle: discord.Role):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    allowed = rank_names(interaction.guild)
    if not allowed:
        return await interaction.response.send_message("Erst `/rangrollen` setzen.", ephemeral=True)
    if rolle.name not in allowed:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(allowed),
            ephemeral=True,
        )
    to_remove = [r for r in person.roles if r.name in allowed and r != rolle]
    try:
        if to_remove:
            await person.remove_roles(*to_remove, reason=f"Beförderung durch {interaction.user}")
        await person.add_roles(rolle, reason=f"Beförderung durch {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message(
            "Bot darf diese Rolle nicht setzen. Bot-Rolle muss über den Rang-Rollen stehen.",
            ephemeral=True,
        )
    await bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "memberliste"])
    await bot.log(interaction.guild, f"{interaction.user.mention} hat {person.mention} nach **{rolle.name}** befördert.")
    await interaction.response.send_message(f"{person.mention} ist jetzt **{rolle.name}**.", ephemeral=True)


@bot.tree.command(name="degradieren", description="Person auf eine niedrigere Rang-Rolle setzen")
async def degradieren(interaction: discord.Interaction, person: discord.Member, rolle: discord.Role):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    allowed = rank_names(interaction.guild)
    if not allowed:
        return await interaction.response.send_message("Erst `/rangrollen` setzen.", ephemeral=True)
    if rolle.name not in allowed:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(allowed),
            ephemeral=True,
        )
    to_remove = [r for r in person.roles if r.name in allowed and r != rolle]
    try:
        if to_remove:
            await person.remove_roles(*to_remove, reason=f"Degradierung durch {interaction.user}")
        await person.add_roles(rolle, reason=f"Degradierung durch {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message(
            "Bot darf diese Rolle nicht setzen. Bot-Rolle muss über den Rang-Rollen stehen.",
            ephemeral=True,
        )
    await bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "memberliste"])
    await bot.log(interaction.guild, f"{interaction.user.mention} hat {person.mention} auf **{rolle.name}** degradiert.")
    await interaction.response.send_message(f"{person.mention} ist jetzt **{rolle.name}**.", ephemeral=True)


async def _set_only_rank(member: discord.Member, rolle: discord.Role, actor: discord.Member, reason: str):
    allowed = rank_names(member.guild)
    to_remove = [r for r in member.roles if r.name in allowed and r != rolle]
    if to_remove:
        await member.remove_roles(*to_remove, reason=reason)
    await member.add_roles(rolle, reason=reason)


@bot.tree.command(name="bloodin", description="Person als Mitarbeiter aufnehmen (Rang-Rolle setzen)")
async def bloodin(interaction: discord.Interaction, person: discord.Member, rolle: discord.Role):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    allowed = rank_names(interaction.guild)
    if not allowed:
        return await interaction.response.send_message("Erst `/rangrollen` setzen.", ephemeral=True)
    if rolle.name not in allowed:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(allowed),
            ephemeral=True,
        )
    try:
        await _set_only_rank(person, rolle, interaction.user, f"Blood In durch {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message(
            "Bot-Rolle muss über den Rang-Rollen stehen.",
            ephemeral=True,
        )
    await bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "memberliste", "dienst"])
    await bot.log(interaction.guild, f"{interaction.user.mention} Blood In: {person.mention} → **{rolle.name}**")
    await interaction.response.send_message(f"{person.mention} ist drin als **{rolle.name}**.", ephemeral=True)


@bot.tree.command(name="bloodout", description="Alle Mitarbeiter-Ränge entfernen")
async def bloodout(interaction: discord.Interaction, person: discord.Member):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    allowed = rank_names(interaction.guild)
    to_remove = [r for r in person.roles if r.name in allowed]
    if not to_remove:
        return await interaction.response.send_message("Die Person hat keinen Mitarbeiter-Rang.", ephemeral=True)
    try:
        await person.remove_roles(*to_remove, reason=f"Blood Out durch {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message(
            "Bot-Rolle muss über den Rang-Rollen stehen.",
            ephemeral=True,
        )
    await bot.db.execute("DELETE FROM attendance WHERE user_id = ?", (person.id,))
    await bot.db.execute("DELETE FROM roster WHERE user_id = ?", (person.id,))
    await bot.db.commit()
    await bot.refresh_panels(interaction.guild, ["mitarbeiter", "rang", "memberliste", "dienst", "aufstellung"])
    await bot.log(interaction.guild, f"{interaction.user.mention} Blood Out: {person.mention}")
    await interaction.response.send_message(f"{person.mention} hat keine Mitarbeiter-Ränge mehr.", ephemeral=True)


@bot.tree.command(name="urlaub_status", description="Urlaub genehmigen oder ablehnen")
@app_commands.describe(status="genehmigt oder abgelehnt")
async def urlaub_status(interaction: discord.Interaction, person: discord.Member, status: str):
    if not is_officer(interaction.user):
        return await interaction.response.send_message("Keine Rechte.", ephemeral=True)
    status = status.lower().strip()
    if status not in {"genehmigt", "abgelehnt"}:
        return await interaction.response.send_message("Status: genehmigt oder abgelehnt", ephemeral=True)
    cur = await bot.db.execute(
        "SELECT id FROM vacations WHERE user_id = ? AND status = 'beantragt' ORDER BY id DESC LIMIT 1",
        (person.id,),
    )
    row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message("Kein offener Antrag.", ephemeral=True)
    await bot.db.execute("UPDATE vacations SET status = ? WHERE id = ?", (status, row["id"]))
    await bot.db.commit()
    await bot.refresh_panels(interaction.guild, ["urlaub"])
    await bot.log(interaction.guild, f"{interaction.user.mention} hat Urlaub von {person.mention} **{status}**.")
    await interaction.response.send_message("Urlaub aktualisiert.", ephemeral=True)


@bot.tree.command(name="sanktion_aufheben", description="Letzte aktive Sanktion einer Person aufheben")
async def sanktion_aufheben(interaction: discord.Interaction, person: discord.Member):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await bot.db.execute(
        "UPDATE sanctions SET active = 0 WHERE user_id = ? AND active = 1",
        (person.id,),
    )
    await bot.db.commit()
    await bot.refresh_panels(interaction.guild, ["sanktionen"])
    await bot.log(interaction.guild, f"{interaction.user.mention} hat Sanktionen von {person.mention} aufgehoben.")
    await interaction.response.send_message("Sanktionen aufgehoben.", ephemeral=True)


@bot.tree.command(name="ophelia_clean", description="Alle Nachrichten von Ophelia Manager löschen")
async def ophelia_clean(interaction: discord.Interaction):
    if not is_high(interaction.user):
        return await interaction.response.send_message("Nur Leadership.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = 0
    for ch in list(interaction.guild.text_channels) + list(interaction.guild.threads):
        try:
            async for msg in ch.history(limit=200):
                if msg.author.id == bot.user.id:
                    await msg.delete()
                    deleted += 1
        except discord.HTTPException:
            continue
    await interaction.followup.send(f"{deleted} Bot-Nachrichten gelöscht.", ephemeral=True)


@bot.tree.command(name="arbeiter_setzen", description="Arbeiter-Daten setzen (kein Ausweis-Foto)")
async def arbeiter_setzen(
    interaction: discord.Interaction,
    person: discord.Member,
    telefon: str = "",
    notiz: str = "",
    geprueft: bool = False,
):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await bot.db.execute(
        """
        INSERT INTO workers(user_id, display_name, phone, verified, note)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            display_name=excluded.display_name,
            phone=excluded.phone,
            verified=excluded.verified,
            note=excluded.note
        """,
        (person.id, person.display_name, telefon or None, 1 if geprueft else 0, notiz or None),
    )
    await bot.db.commit()
    await bot.refresh_panels(interaction.guild, ["arbeiter"])
    await interaction.response.send_message("Arbeiter gespeichert.", ephemeral=True)


@bot.tree.command(name="arbeiter_entfernen", description="Arbeiter austragen")
async def arbeiter_entfernen(interaction: discord.Interaction, person: discord.Member):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await bot.db.execute("DELETE FROM workers WHERE user_id = ?", (person.id,))
    await bot.db.commit()
    await bot.refresh_panels(interaction.guild, ["arbeiter"])
    await bot.log(interaction.guild, f"{interaction.user.mention} hat {person.mention} als Arbeiter entfernt.")
    await interaction.response.send_message("Arbeiter entfernt.", ephemeral=True)


async def start_web():
    from webapp import make_app
    import uvicorn

    app = make_app(bot)
    port = int(os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def runner():
    token = os.getenv("DISCORD_TOKEN")
    if not token or token.startswith("hier_"):
        print("DISCORD_TOKEN fehlt. Trage ihn in die Datei .env ein.")
        # Website trotzdem starten, damit das Dashboard erreichbar ist
        await start_web()
        return
    await asyncio.gather(bot.start(token), start_web())


if __name__ == "__main__":
    asyncio.run(runner())
