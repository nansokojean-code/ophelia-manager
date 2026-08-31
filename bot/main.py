import asyncio
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
load_dotenv(ROOT / ".env")

import database
import panels
import views
from ranks import RANK_ROLE_NAMES, is_leader, is_officer


intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.guilds = True
intents.message_content = True

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
    "urlaub",
    "infos",
    "arbeiter",
    "tickets",
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
        self.add_view(views.SanktionView(self))
        self.add_view(views.AusruestungView(self))
        self.add_view(views.UrlaubView(self))
        self.add_view(views.RangView(self))
        self.add_view(views.TicketView(self))
        await self.tree.sync()

    async def log(self, guild: discord.Guild, text: str):
        raw = await database.get_setting(self.db, f"log_channel:{guild.id}")
        if not raw:
            return
        ch = guild.get_channel(int(raw))
        if ch:
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass

    async def refresh_panels(self, guild: discord.Guild, names=None):
        mapping = {
            "mitarbeiter": ("mitarbeiter", panels.embed_mitarbeiter(guild), None),
            "memberliste": ("memberliste", panels.embed_memberliste(guild), None),
            "rang": ("rang", panels.embed_rangsystem(guild), views.RangView(self)),
            "aufstellung": ("aufstellung", panels.embed_aufstellung(guild, self.db), views.AufstellungView(self)),
            "dienst": ("dienst", panels.embed_dienststatus(guild, self.db), views.DienstView(self)),
            "katalog": ("katalog", panels.embed_katalog(self.db), None),
            "sanktionen": ("sanktionen", panels.embed_sanktionen(guild, self.db), views.SanktionView(self)),
            "ausruestung": ("ausruestung", panels.embed_ausruestung(guild, self.db), views.AusruestungView(self)),
            "lager": ("lager", panels.embed_lager(self.db), views.LagerView(self)),
            "urlaub": ("urlaub", panels.embed_urlaub(guild, self.db), views.UrlaubView(self)),
            "infos": ("infos", panels.embed_infos(self.db), None),
            "arbeiter": ("arbeiter", panels.embed_arbeiter(guild, self.db), None),
            "tickets": ("tickets", panels.embed_tickets(), views.TicketView(self)),
        }
        targets = names or list(mapping.keys())
        for name in targets:
            key, embed_coro, view = mapping[name]
            row = await database.get_panel(self.db, f"{guild.id}:{key}")
            if not row:
                continue
            ch = guild.get_channel(row["channel_id"])
            if not ch:
                continue
            try:
                msg = await ch.fetch_message(row["message_id"])
            except discord.NotFound:
                continue
            embed = await embed_coro
            try:
                await msg.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass

    async def post_panel(self, channel: discord.TextChannel, key: str):
        guild = channel.guild
        builders = {
            "mitarbeiter": (panels.embed_mitarbeiter(guild), None),
            "memberliste": (panels.embed_memberliste(guild), None),
            "rang": (panels.embed_rangsystem(guild), views.RangView(self)),
            "aufstellung": (panels.embed_aufstellung(guild, self.db), views.AufstellungView(self)),
            "dienst": (panels.embed_dienststatus(guild, self.db), views.DienstView(self)),
            "katalog": (panels.embed_katalog(self.db), None),
            "sanktionen": (panels.embed_sanktionen(guild, self.db), views.SanktionView(self)),
            "ausruestung": (panels.embed_ausruestung(guild, self.db), views.AusruestungView(self)),
            "lager": (panels.embed_lager(self.db), views.LagerView(self)),
            "urlaub": (panels.embed_urlaub(guild, self.db), views.UrlaubView(self)),
            "infos": (panels.embed_infos(self.db), None),
            "arbeiter": (panels.embed_arbeiter(guild, self.db), None),
            "tickets": (panels.embed_tickets(), views.TicketView(self)),
        }
        embed_coro, view = builders[key]
        embed = await embed_coro
        msg = await channel.send(embed=embed, view=view)
        await database.set_panel(self.db, f"{guild.id}:{key}", channel.id, msg.id)
        return msg


bot = ClubBot()


@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Ophelia Manager")
    )
    print(f"Ophelia Manager online als {bot.user} ({bot.user.id})")
    for g in bot.guilds:
        try:
            await bot.refresh_panels(g)
        except Exception as e:
            print("Refresh error", g.id, e)


@bot.event
async def on_member_join(member: discord.Member):
    await bot.refresh_panels(member.guild, ["memberliste", "mitarbeiter", "dienst"])
    await bot.log(member.guild, f"{member.mention} ist dem Server beigetreten.")


@bot.event
async def on_member_remove(member: discord.Member):
    await bot.refresh_panels(member.guild, ["memberliste", "mitarbeiter", "dienst", "aufstellung", "rang"])
    await bot.log(member.guild, f"**{member}** hat den Server verlassen.")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles or before.nick != after.nick or before.display_name != after.display_name:
        await bot.refresh_panels(
            after.guild,
            ["memberliste", "mitarbeiter", "rang", "dienst", "aufstellung", "ausruestung", "arbeiter"],
        )


@bot.tree.command(name="setup", description="Eine Live-Liste in diesen Kanal setzen")
@app_commands.describe(panel="Welche Liste soll hier stehen?")
@app_commands.choices(panel=[app_commands.Choice(name=n, value=n) for n in PANEL_NAMES])
async def setup_cmd(interaction: discord.Interaction, panel: app_commands.Choice[str]):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await bot.post_panel(interaction.channel, panel.value)
    await interaction.followup.send(
        f"Ophelia Manager hat **{panel.value}** hier gepostet. Die Liste bleibt aktuell.",
        ephemeral=True,
    )


@bot.tree.command(name="logkanal", description="Log-Kanal festlegen")
async def logkanal(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    await database.set_setting(bot.db, f"log_channel:{interaction.guild.id}", str(kanal.id))
    await interaction.response.send_message(f"Log-Kanal ist jetzt {kanal.mention}.", ephemeral=True)


@bot.tree.command(name="befoerdern", description="Person auf eine Rang-Rolle setzen")
async def befoerdern(interaction: discord.Interaction, person: discord.Member, rolle: discord.Role):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    if rolle.name not in RANK_ROLE_NAMES:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(RANK_ROLE_NAMES),
            ephemeral=True,
        )
    to_remove = [r for r in person.roles if r.name in RANK_ROLE_NAMES and r != rolle]
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
    if rolle.name not in RANK_ROLE_NAMES:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(RANK_ROLE_NAMES),
            ephemeral=True,
        )
    to_remove = [r for r in person.roles if r.name in RANK_ROLE_NAMES and r != rolle]
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
    to_remove = [r for r in member.roles if r.name in RANK_ROLE_NAMES and r != rolle]
    if to_remove:
        await member.remove_roles(*to_remove, reason=reason)
    await member.add_roles(rolle, reason=reason)


@bot.tree.command(name="bloodin", description="Person als Mitarbeiter aufnehmen (Rang-Rolle setzen)")
async def bloodin(interaction: discord.Interaction, person: discord.Member, rolle: discord.Role):
    if not is_leader(interaction.user):
        return await interaction.response.send_message("Nur Leitung.", ephemeral=True)
    if rolle.name not in RANK_ROLE_NAMES:
        return await interaction.response.send_message(
            "Rolle muss eine Rang-Rolle sein: " + ", ".join(RANK_ROLE_NAMES),
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
    to_remove = [r for r in person.roles if r.name in RANK_ROLE_NAMES]
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
    port = int(os.getenv("WEB_PORT", "8080"))
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
