import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database
from ranks import hidden_from_lists, highest_rank, rank_names, set_areas, set_guild_roles

TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
UPLOADS = Path(__file__).resolve().parent.parent / "data" / "uploads"


def _lines(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$", 2)
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _new_password(length=12):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_app(bot):
    app = FastAPI(title="Ophelia Manager")
    templates = Jinja2Templates(directory=str(TEMPLATES))
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")

    async def ensure_owner():
        if not bot.db:
            return
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM web_users")
        if (await cur.fetchone())["c"]:
            return
        username = os.getenv("WEB_OWNER_USERNAME", "owner").strip() or "owner"
        password = os.getenv("WEB_PASSWORD", "").strip()
        if not password:
            password = _new_password()
            print(f"WEB_OWNER_USERNAME={username}")
            print(f"WEB_OWNER_PASSWORD={password}")
        await bot.db.execute(
            "INSERT INTO web_users(username,password_hash,role,must_change_password) VALUES(?,?,?,0)",
            (username.lower(), _hash_password(password), "owner"),
        )
        await bot.db.commit()

    async def current_user(request: Request):
        if not bot.db:
            return None
        sid = request.cookies.get("clubbot_session")
        if not sid:
            return None
        cur = await bot.db.execute(
            "SELECT u.* FROM web_sessions s JOIN web_users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at > ?",
            (sid, datetime.utcnow().isoformat()),
        )
        return await cur.fetchone()

    async def require_user(request: Request):
        await ensure_owner()
        return await current_user(request)

    def guild():
        selected = getattr(bot, "web_selected_guild_id", None)
        if selected:
            g = bot.get_guild(int(selected))
            if g:
                return g
        return bot.guilds[0] if bot.guilds else None

    async def apply_saved_roles():
        ranks = _lines(await database.get_setting(bot.db, "web_ranks", "") or "")
        leaders = _lines(await database.get_setting(bot.db, "web_leaders", "") or "")
        officers = _lines(await database.get_setting(bot.db, "web_officers", "") or "")
        areas = _lines(await database.get_setting(bot.db, "web_areas", "") or "")
        if areas:
            set_areas(areas)
        if ranks:
            for g in bot.guilds:
                set_guild_roles(g.id, ranks, leaders or None, officers or None)
                await database.set_setting(bot.db, f"ranks:{g.id}", "|".join(ranks))
                if leaders:
                    await database.set_setting(bot.db, f"leaders:{g.id}", "|".join(leaders))
                if officers:
                    await database.set_setting(bot.db, f"officers:{g.id}", "|".join(officers))

    async def base_context(request: Request, active: str, title: str, subtitle: str):
        user = await require_user(request)
        if not user:
            return None, None
        g = guild()
        cur = await bot.db.execute("SELECT panel_key,label,source FROM web_builder_panels WHERE enabled=1 ORDER BY sort_order,id")
        nav_panels = await cur.fetchall()
        ctx = {
            "request": request,
            "user": user,
            "active": active,
            "page_title": title,
            "page_subtitle": subtitle,
            "guild_name": g.name if g else "Discord nicht verbunden",
            "guild_id": g.id if g else None,
            "online": bool(bot.user),
            "nav_panels": nav_panels,
        }
        return user, ctx

    async def auth_or_login(request: Request):
        user = await require_user(request)
        if not user:
            return templates.TemplateResponse("login.html", {"request": request, "error": ""})
        if user["must_change_password"]:
            return templates.TemplateResponse("change_password.html", {"request": request, "user": user, "error": ""})
        return None

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user = await require_user(request)
        if user and not bool(user["onboarding_seen"]):
            return RedirectResponse("/tutorial", status_code=303)
        if user and user["role"] == "owner" and len(bot.guilds) > 1 and not request.cookies.get("clubbot_guild"):
            return RedirectResponse("/servers", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/tutorial", response_class=HTMLResponse)
    async def tutorial(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user = await require_user(request)
        g = guild()
        return templates.TemplateResponse("tutorial.html", {
            "request": request,
            "user": user,
            "guild_name": g.name if g else "Dein Discord-Server",
            "is_owner": bool(user and user["role"] == "owner"),
        })

    @app.post("/tutorial/complete")
    async def tutorial_complete(request: Request):
        user = await require_user(request)
        if not user:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute("UPDATE web_users SET onboarding_seen=1 WHERE id=?", (user["id"],))
        await bot.db.commit()
        if user["role"] == "owner" and len(bot.guilds) > 1 and not request.cookies.get("clubbot_guild"):
            return RedirectResponse("/servers", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/servers", response_class=HTMLResponse)
    async def server_select(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user = await require_user(request)
        if not user or user["role"] != "owner":
            return RedirectResponse("/dashboard", status_code=303)
        cards = []
        for g in bot.guilds:
            cards.append({"id": g.id, "name": g.name, "members": g.member_count or 0, "icon": str(g.icon.url) if g.icon else ""})
        return templates.TemplateResponse("servers.html", {"request": request, "user": user, "servers": cards})

    @app.post("/servers/select")
    async def server_choose(request: Request, guild_id: int = Form(...)):
        user = await require_user(request)
        if not user or user["role"] != "owner":
            return RedirectResponse("/dashboard", status_code=303)
        if not any(g.id == guild_id for g in bot.guilds):
            return RedirectResponse("/servers", status_code=303)
        bot.web_selected_guild_id = guild_id
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("clubbot_guild", str(guild_id), samesite="lax", max_age=86400*30)
        return resp

    @app.get("/systemcheck", response_class=HTMLResponse)
    async def system_check(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "systemcheck", "System- & Konfigurationsprüfung", "Fehlende Berechtigungen, Discord-Ressourcen und Moduleinstellungen prüfen.")
        g = guild()
        checks=[]
        score=100
        if not g:
            checks.append({"level":"critical","title":"Discord-Server nicht verbunden","text":"Der Bot ist aktuell mit keinem Server verbunden."}); score-=50
        else:
            me=g.me
            if me and not me.guild_permissions.manage_roles:
                checks.append({"level":"warning","title":"Rollen verwalten fehlt","text":"Der Bot kann Rollen ohne die Berechtigung 'Rollen verwalten' nicht ändern."}); score-=10
            if me and not me.guild_permissions.send_messages:
                checks.append({"level":"critical","title":"Nachrichten senden fehlt","text":"Der Bot benötigt die Berechtigung Nachrichten zu senden."}); score-=25
            if me and not me.guild_permissions.embed_links:
                checks.append({"level":"warning","title":"Links einbetten fehlt","text":"Embeds können sonst unvollständig dargestellt werden."}); score-=5
            if me:
                above=[r for r in g.roles if not r.is_default() and r.position >= me.top_role.position and not r.managed]
                if above:
                    checks.append({"level":"info","title":"Bot-Rollenposition prüfen","text":"Der Bot kann nur Rollen unterhalb seiner höchsten Rolle verwalten."}); score-=2
        try:
            cur=await bot.db.execute("SELECT COUNT(*) AS c FROM web_module_settings WHERE module_enabled=0")
            disabled=(await cur.fetchone())["c"]
            if disabled:
                checks.append({"level":"info","title":f"{disabled} Module deaktiviert","text":"Deaktivierte Module senden keine automatischen Panels."}); score-=min(disabled,5)
        except Exception:
            pass
        if not checks:
            checks=[{"level":"ok","title":"Alles bereit","text":"Keine Konfigurationsprobleme gefunden."}]
        ctx.update(checks=checks, score=max(0,score))
        return templates.TemplateResponse("systemcheck.html", ctx)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "dashboard", "Dashboard", "Alle wichtigen Bot- und Serverdaten auf einen Blick.")
        g = guild()
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM web_builder_panels WHERE enabled=1")
        panel_count = (await cur.fetchone())["c"]
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM web_users")
        user_count = (await cur.fetchone())["c"]
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM sanctions WHERE active=1")
        sanctions = (await cur.fetchone())["c"]
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM catalog")
        catalog_count = (await cur.fetchone())["c"]
        cur = await bot.db.execute("SELECT COUNT(*) AS c FROM inventory")
        inventory_count = (await cur.fetchone())["c"]

        member_count = g.member_count if g else 0
        online_count = 0
        bot_count = 0
        staff_count = 0
        role_counts = []
        attendance_counts = {"angemeldet": 0, "abgemeldet": 0, "offen": 0}
        if g:
            bot_count = sum(1 for m in g.members if m.bot)
            online_count = sum(1 for m in g.members if not m.bot and str(getattr(m, "status", "offline")) != "offline")
            staff = [m for m in g.members if not m.bot and not hidden_from_lists(m) and highest_rank(m)]
            staff_count = len(staff)
            cur = await bot.db.execute("SELECT user_id,status FROM attendance")
            status_by = {r["user_id"]: r["status"] for r in await cur.fetchall()}
            for m in staff:
                st = status_by.get(m.id, "offen")
                attendance_counts[st if st in attendance_counts else "offen"] += 1
            ranked_roles = [r for r in g.roles if not r.is_default() and not r.managed]
            ranked_roles.sort(key=lambda r: r.position, reverse=True)
            for r in ranked_roles[:5]:
                role_counts.append({"name": r.name, "count": len(r.members)})

        # Lightweight activity feed from real DB changes.
        activity = []
        try:
            cur = await bot.db.execute("SELECT user_id,status,updated_at FROM attendance ORDER BY rowid DESC LIMIT 4")
            for r in await cur.fetchall():
                member = g.get_member(r["user_id"]) if g else None
                activity.append({"icon":"◉", "title": member.display_name if member else str(r["user_id"]), "text": f"Aufstellung: {r['status']}", "time": r["updated_at"] or ""})
        except Exception:
            pass
        try:
            cur = await bot.db.execute("SELECT kind,reason,created_at FROM sanctions ORDER BY id DESC LIMIT 3")
            for r in await cur.fetchall():
                activity.append({"icon":"⚠", "title": r["kind"], "text": r["reason"], "time": r["created_at"] or ""})
        except Exception:
            pass
        activity = activity[:6]

        latency_ms = round(bot.latency * 1000) if getattr(bot, "latency", None) is not None else 0
        started = getattr(bot, "started_at", None)
        uptime = "–"
        if started:
            now = datetime.now(TZ) if 'TZ' in globals() and TZ else datetime.now()
            try:
                delta = now - started
                days = delta.days
                hours = delta.seconds // 3600
                mins = (delta.seconds % 3600) // 60
                uptime = f"{days}T {hours}Std {mins}Min" if days else f"{hours}Std {mins}Min"
            except Exception:
                pass

        ctx.update(
            panel_count=panel_count, user_count=user_count, sanctions=sanctions, staff_count=staff_count,
            attendance_counts=attendance_counts, member_count=member_count, online_count=online_count,
            channel_count=len(g.channels) if g else 0, role_count=max(0, len(g.roles)-1) if g else 0, bot_count=bot_count,
            latency_ms=latency_ms, uptime=uptime, activity=activity, role_counts=role_counts,
            catalog_count=catalog_count, inventory_count=inventory_count,
        )
        return templates.TemplateResponse("dashboard.html", ctx)

    @app.get("/aufstellung", response_class=HTMLResponse)
    async def aufstellung(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "aufstellung", "Aufstellung", "Teilnehmer, Status, Ränge, Uhrzeit und Discord-Buttons verwalten.")
        g = guild()
        people = []
        all_members = []
        rank_list = rank_names(g) if g else []
        if g:
            cur = await bot.db.execute("SELECT user_id,status,reason,updated_at FROM attendance")
            rows = {r["user_id"]: r for r in await cur.fetchall()}
            for m in g.members:
                if m.bot or hidden_from_lists(m):
                    continue
                rank = highest_rank(m)
                all_members.append({"id": m.id, "name": m.display_name, "rank": rank or ""})
                if not rank:
                    continue
                row = rows.get(m.id)
                people.append({
                    "id": m.id,
                    "name": m.display_name,
                    "mention": m.mention,
                    "rank": rank,
                    "status": row["status"] if row else "offen",
                    "reason": row["reason"] if row else "",
                })
        order = {"angemeldet": 0, "abgemeldet": 1, "offen": 2}
        people.sort(key=lambda p: (order.get(p["status"], 2), p["name"].lower()))
        gid = g.id if g else 0
        time_value = await database.get_setting(bot.db, f"aufstellung_time:{gid}", "18:00")
        send_time = await database.get_setting(bot.db, f"aufstellung_send_time:{gid}", "17:00")
        send_days = await database.get_setting(bot.db, f"aufstellung_send_days:{gid}", "0,1,2,3,4,5,6")
        reset_on_send = await database.get_setting(bot.db, f"aufstellung_reset_on_send:{gid}", "0")
        layout = await database.get_setting(bot.db, f"aufstellung_layout:{gid}", "embed")
        title_value = await database.get_setting(bot.db, f"aufstellung_title:{gid}", "Aufstellung")
        description_value = await database.get_setting(bot.db, f"aufstellung_description:{gid}", "Seid pünktlich da.")
        ping_value = await database.get_setting(bot.db, f"aufstellung_ping:{gid}", "Ophelia")
        footer_value = await database.get_setting(bot.db, f"aufstellung_footer:{gid}", "Automatische Aktualisierung · Buttons unten")
        color_value = await database.get_setting(bot.db, f"aufstellung_color:{gid}", "#2B2D31")
        cur = await bot.db.execute("SELECT button_key,label,style,enabled FROM web_panel_buttons WHERE panel_key='aufstellung' ORDER BY sort_order,id")
        buttons = await cur.fetchall()
        groups = {"angemeldet": [], "abgemeldet": [], "offen": []}
        for person in people:
            groups.get(person["status"], groups["offen"]).append(person)
        ctx.update(people=people, groups=groups, all_members=all_members, rank_list=rank_list, time_value=time_value, buttons=buttons,
                   send_time=send_time, send_days=send_days.split(",") if send_days else [], reset_on_send=reset_on_send, layout=layout,
                   title_value=title_value, description_value=description_value, ping_value=ping_value, footer_value=footer_value, color_value=color_value)
        return templates.TemplateResponse("aufstellung.html", ctx)

    @app.get("/members", response_class=HTMLResponse)
    async def members(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "members", "Member", "Discord-Mitglieder und ihre Ophelia-Ränge verwalten.")
        g = guild()
        rows = []
        if g:
            for m in g.members:
                if m.bot or hidden_from_lists(m):
                    continue
                rank = highest_rank(m)
                if rank:
                    rows.append({"id": m.id, "name": m.display_name, "rank": rank, "status": str(m.status)})
        rows.sort(key=lambda x: (rank_names(g).index(x["rank"]) if x["rank"] in rank_names(g) else 99, x["name"].lower())) if g else None
        ctx.update(members=rows, rank_list=rank_names(g) if g else [])
        return templates.TemplateResponse("members.html", ctx)

    @app.get("/ranks", response_class=HTMLResponse)
    async def ranks_page(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "ranks", "Ränge", "Rangrollen, Leitung und Reihenfolge für den Bot festlegen.")
        ctx.update(
            ranks=await database.get_setting(bot.db, "web_ranks", "") or "",
            leaders=await database.get_setting(bot.db, "web_leaders", "") or "",
            officers=await database.get_setting(bot.db, "web_officers", "") or "",
            areas=await database.get_setting(bot.db, "web_areas", "Bar\nTür\nService\nBüro\nNicht eingeteilt") or "",
        )
        return templates.TemplateResponse("ranks.html", ctx)

    @app.get("/content", response_class=HTMLResponse)
    async def content_page(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "content", "Inhalte", "Infos, Regeln, Notizen, Status und Katalog getrennt bearbeiten.")
        cur = await bot.db.execute("SELECT id,title,body,updated_at FROM infos ORDER BY id DESC")
        infos = await cur.fetchall()
        cur = await bot.db.execute("SELECT id,title,body,created_at FROM notes ORDER BY id DESC")
        notes = await cur.fetchall()
        cur = await bot.db.execute("SELECT id,name,description FROM catalog ORDER BY id")
        catalog = await cur.fetchall()
        ctx.update(infos=infos, notes=notes, catalog=catalog,
                   rules=await database.get_setting(bot.db, "regeln", "") or "",
                   club_status=await database.get_setting(bot.db, "club_status", "geschlossen") or "geschlossen",
                   status_text=await database.get_setting(bot.db, "club_status_text", "") or "")
        return templates.TemplateResponse("content.html", ctx)

    @app.get("/panels", response_class=HTMLResponse)
    async def panels_page(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "panels", "Setup-Studio", "Alle vorhandenen Discord-Setups mit echten Bot-Daten bearbeiten, Vorschau prüfen und neue /setup-Setups erstellen.")
        cur = await bot.db.execute("SELECT * FROM web_builder_panels ORDER BY sort_order,id")
        raw_panels = await cur.fetchall()
        channels = []
        g = guild()
        if g and g.me:
            channels = [c for c in g.text_channels if c.permissions_for(g.me).send_messages]

        # Read the CURRENT bot embed/view, not empty placeholder fields.
        live_by = {}
        if g:
            for p in raw_panels:
                if p["source"] != "bot":
                    continue
                try:
                    factory = bot._panel_builder(g, p["panel_key"])
                    if not factory:
                        continue
                    embed = await factory[0]()
                    view = factory[1]()
                    color = f"#{getattr(getattr(embed, 'color', None), 'value', 0x5865F2):06X}"
                    footer = getattr(getattr(embed, "footer", None), "text", "") or ""
                    image_url = getattr(getattr(embed, "image", None), "url", "") or ""
                    thumb_url = getattr(getattr(embed, "thumbnail", None), "url", "") or ""
                    live_by[p["panel_key"]] = {
                        "title": embed.title or p["label"],
                        "description": embed.description or "",
                        "color": color,
                        "footer": footer,
                        "image_url": image_url,
                        "thumbnail_url": thumb_url,
                        "fields": [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields],
                    }
                    # Seed editable button rows from the real Discord view.
                    if view:
                        for item in getattr(view, "children", []):
                            cid = getattr(item, "custom_id", None)
                            label = getattr(item, "label", None)
                            if not cid or not label:
                                continue
                            style = str(getattr(getattr(item, "style", None), "name", "secondary"))
                            await bot.db.execute(
                                "INSERT INTO web_panel_buttons(panel_key,button_key,label,style,enabled,sort_order) VALUES(?,?,?,?,1,999) "
                                "ON CONFLICT(panel_key,button_key) DO NOTHING",
                                (p["panel_key"], cid, label, style),
                            )
                except Exception as exc:
                    live_by[p["panel_key"]] = {"error": str(exc)}
            await bot.db.commit()
            await bot.load_web_button_config()

        fields_by, actions_by, buttons_by = {}, {}, {}
        cur = await bot.db.execute("SELECT * FROM web_setup_fields ORDER BY panel_key,sort_order,id")
        for r in await cur.fetchall(): fields_by.setdefault(r["panel_key"], []).append(r)
        cur = await bot.db.execute("SELECT * FROM web_setup_actions ORDER BY panel_key,sort_order,id")
        for r in await cur.fetchall(): actions_by.setdefault(r["panel_key"], []).append(r)
        cur = await bot.db.execute("SELECT * FROM web_panel_buttons ORDER BY panel_key,sort_order,id")
        for r in await cur.fetchall(): buttons_by.setdefault(r["panel_key"], []).append(r)

        # Convert rows to dicts and provide effective current bot values to the template.
        panels = []
        for row in raw_panels:
            d = dict(row)
            live = live_by.get(d["panel_key"], {})
            d["effective_title"] = d["title_override"].strip() or live.get("title", d["label"])
            d["effective_description"] = d["description_override"].strip() or live.get("description", "")
            d["effective_footer"] = d["footer_text"].strip() or live.get("footer", "")
            d["effective_color"] = d["color_hex"] if d["color_hex"] and d["color_hex"] != "#5865F2" else live.get("color", d["color_hex"] or "#5865F2")
            d["live_fields"] = live.get("fields", [])
            d["live_image_url"] = live.get("image_url", "")
            d["live_thumbnail_url"] = live.get("thumbnail_url", "")
            panels.append(d)
        ctx.update(builder_panels=panels, channels=channels, fields_by=fields_by, actions_by=actions_by, buttons_by=buttons_by)
        return templates.TemplateResponse("panels.html", ctx)

    async def _panel_live(g, row):
        live={"title": row["label"], "description":"", "color":"#2B6EA6", "footer":"", "image_url":"", "thumbnail_url":"", "fields":[]}
        if g and row["source"] == "bot":
            try:
                factory = bot._panel_builder(g, row["panel_key"])
                if factory:
                    embed = await factory[0]()
                    view = factory[1]()
                    live.update({
                        "title": embed.title or row["label"],
                        "description": embed.description or "",
                        "color": f"#{getattr(getattr(embed,'color',None),'value',0x2B6EA6):06X}",
                        "footer": getattr(getattr(embed,'footer',None),'text','') or '',
                        "image_url": getattr(getattr(embed,'image',None),'url','') or '',
                        "thumbnail_url": getattr(getattr(embed,'thumbnail',None),'url','') or '',
                        "fields": [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields],
                    })
                    if view:
                        for n,item in enumerate(getattr(view,'children',[]),1):
                            cid=getattr(item,'custom_id',None); label=getattr(item,'label',None)
                            if cid and label:
                                style=str(getattr(getattr(item,'style',None),'name','secondary'))
                                await bot.db.execute("INSERT INTO web_panel_buttons(panel_key,button_key,label,style,enabled,sort_order) VALUES(?,?,?,?,1,?) ON CONFLICT(panel_key,button_key) DO NOTHING", (row['panel_key'],cid,label,style,n*10))
                        await bot.db.commit(); await bot.load_web_button_config()
            except Exception as exc:
                live["error"] = str(exc)
        return live

    @app.get("/module/{panel_key}", response_class=HTMLResponse)
    async def module_page(request: Request, panel_key: str):
        gate = await auth_or_login(request)
        if gate: return gate
        cur=await bot.db.execute("SELECT * FROM web_builder_panels WHERE panel_key=?", (panel_key,))
        row=await cur.fetchone()
        if not row: return RedirectResponse("/panels", status_code=303)
        user, ctx = await base_context(request, "module:"+panel_key, row["label"], "Funktion, Inhalt, Darstellung, Bilder, Buttons und Berechtigungen verwalten.")
        g=guild(); live=await _panel_live(g,row)
        cur=await bot.db.execute("SELECT module_enabled,image_enabled FROM web_module_settings WHERE panel_key=?",(panel_key,)); ms=await cur.fetchone()
        cur=await bot.db.execute("SELECT * FROM web_panel_buttons WHERE panel_key=? ORDER BY sort_order,id",(panel_key,)); btns=[dict(x) for x in await cur.fetchall()]
        for b in btns:
            c=await bot.db.execute("SELECT role_id FROM web_button_roles WHERE panel_key=? AND button_key=?",(panel_key,b['button_key']))
            b['role_ids']={str(x['role_id']) for x in await c.fetchall()}
        roles=[] if not g else [r for r in sorted(g.roles,key=lambda r:r.position,reverse=True) if not r.is_default() and not r.managed]
        d=dict(row)
        d['effective_title']=d['title_override'].strip() or live.get('title',d['label'])
        d['effective_description']=d['description_override'].strip() or live.get('description','')
        d['effective_footer']=d['footer_text'].strip() or live.get('footer','')
        d['effective_color']=d['color_hex'] if d['color_hex'] and d['color_hex']!='#5865F2' else live.get('color','#2B6EA6')
        d['live_fields']=live.get('fields',[]); d['live_image_url']=live.get('image_url',''); d['live_thumbnail_url']=live.get('thumbnail_url','')
        member_options=[]
        if g:
            member_options=[{'id':m.id,'name':m.display_name} for m in g.members if not m.bot]
            member_options.sort(key=lambda x:x['name'].lower())
        ctx.update(panel=d, buttons=btns, roles=roles, member_options=member_options, module_enabled=(ms['module_enabled'] if ms else 1), image_enabled=(ms['image_enabled'] if ms else 1))
        return templates.TemplateResponse("module.html",ctx)

    @app.post("/module/{panel_key}/settings")
    async def module_settings(request: Request, panel_key: str):
        user=await require_user(request)
        if not user: return RedirectResponse("/",status_code=303)
        f=await request.form()
        await bot.db.execute("INSERT INTO web_module_settings(panel_key,module_enabled,image_enabled) VALUES(?,?,?) ON CONFLICT(panel_key) DO UPDATE SET module_enabled=excluded.module_enabled,image_enabled=excluded.image_enabled",(panel_key,1 if f.get('module_enabled') else 0,1 if f.get('image_enabled') else 0))
        await bot.db.execute("UPDATE web_builder_panels SET title_override=?,description_override=?,color_hex=?,footer_text=? WHERE panel_key=?",(str(f.get('title','')).strip(),str(f.get('description','')).strip(),str(f.get('color','#2B6EA6')).strip() or '#2B6EA6',str(f.get('footer','')).strip(),panel_key))
        await bot.db.commit()
        g=guild()
        if g:
            try: await bot.refresh_panels(g,[panel_key])
            except Exception: pass
        return RedirectResponse(f"/module/{panel_key}?ok=Gespeichert",status_code=303)

    @app.post("/module/{panel_key}/button")
    async def module_button(request: Request, panel_key: str):
        user=await require_user(request)
        if not user: return RedirectResponse("/",status_code=303)
        f=await request.form(); key=str(f.get('button_key','')); roles=[int(x) for x in f.getlist('role_ids') if str(x).isdigit()]
        style=str(f.get('style','secondary')); style=style if style in {'primary','secondary','success','danger'} else 'secondary'
        await bot.db.execute("UPDATE web_panel_buttons SET label=?,style=?,enabled=? WHERE panel_key=? AND button_key=?",(str(f.get('label','Button')).strip()[:80] or 'Button',style,1 if f.get('enabled') else 0,panel_key,key))
        await bot.db.execute("DELETE FROM web_button_roles WHERE panel_key=? AND button_key=?",(panel_key,key))
        if roles:
            await bot.db.executemany("INSERT INTO web_button_roles(panel_key,button_key,role_id) VALUES(?,?,?)",[(panel_key,key,r) for r in roles])
        await bot.db.commit(); await bot.load_web_button_config()
        g=guild()
        if g:
            try: await bot.refresh_panels(g,[panel_key])
            except Exception: pass
        return RedirectResponse(f"/module/{panel_key}#buttons",status_code=303)

    @app.post("/module/sanktionen/create")
    async def web_sanction_create(request: Request, user_id: int = Form(...), was: str = Form(...), wieviel: str = Form(...), bis: str = Form("")):
        user=await require_user(request)
        if not user: return RedirectResponse("/",status_code=303)
        g=guild()
        if not g: return RedirectResponse("/module/sanktionen?error=Discord+nicht+verbunden",status_code=303)
        member=g.get_member(user_id)
        if not member: return RedirectResponse("/module/sanktionen?error=Person+nicht+gefunden",status_code=303)
        await bot.db.execute("INSERT INTO sanctions(user_id,kind,reason,until_text,by_id,active,created_at) VALUES(?,?,?,?,?,1,?)",(user_id,was.strip(),wieviel.strip(),bis.strip() or None,0,datetime.now().strftime("%d.%m.%Y %H:%M")))
        await bot.db.commit(); cur=await bot.db.execute("SELECT last_insert_rowid() AS i"); sid=(await cur.fetchone())["i"]
        import discord
        e=discord.Embed(title="Sanktion",color=0xC0392B)
        e.description=f"**Wer:** {member.mention}\n**Was:** {was.strip()}\n**Wie viel:** {wieviel.strip()}\n**Bis:** {bis.strip() or '-'}"
        e.set_footer(text=f"SID:{sid}")
        prow=await database.get_panel(bot.db,f"{g.id}:sanktionen")
        ch=g.get_channel(prow['channel_id']) if prow else None
        if ch:
            try:
                from views import SanktionPayView
                await ch.send(embed=e,view=SanktionPayView())
            except Exception as exc:
                print('web sanction message failed',repr(exc))
        await bot.refresh_panels(g,["sanktionen"])
        return RedirectResponse("/module/sanktionen?ok=Sanktion+als+eigene+Nachricht+gepostet",status_code=303)

    @app.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "users", "Benutzer", "Zugänge für das Webpanel verwalten.")
        if user["role"] != "owner":
            return RedirectResponse("/dashboard", status_code=303)
        cur = await bot.db.execute("SELECT id,username,role,must_change_password FROM web_users ORDER BY username")
        ctx["users"] = await cur.fetchall()
        return templates.TemplateResponse("users.html", ctx)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        gate = await auth_or_login(request)
        if gate:
            return gate
        user, ctx = await base_context(request, "settings", "Einstellungen", "Allgemeine Verbindung und Serverinformationen.")
        if user["role"] != "owner":
            return RedirectResponse("/dashboard", status_code=303)
        g = guild()
        ctx.update(guild_id=g.id if g else "-", bot_name=str(bot.user) if bot.user else "Offline",
                   web_port=os.getenv("WEB_PORT", "8080"))
        return templates.TemplateResponse("settings.html", ctx)

    @app.post("/settings/import-db")
    async def import_legacy_db(request: Request, db_file: UploadFile = File(...)):
        user = await require_user(request)
        if not user or user["role"] != "owner":
            return RedirectResponse("/settings", status_code=303)
        data = await db_file.read()
        if not data or len(data) > 100 * 1024 * 1024:
            return RedirectResponse("/settings?error=Datei+ungültig", status_code=303)
        tmp = None
        imported = 0
        tables = [
            "settings","panels","attendance","roster","catalog","warnings","sanctions","inventory","inventory_log",
            "equipment","workers","vacations","infos","equipment_items","activity","notes","blacklist","lootdrops",
            "routes","einkauf","routechecks","clip_channels","activity_fails","abgaben"
        ]
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as fh:
                fh.write(data); tmp = fh.name
            src = sqlite3.connect(tmp)
            src.row_factory = sqlite3.Row
            src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for table in tables:
                if table not in src_tables:
                    continue
                src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
                dst_cols = [r[1] for r in await (await bot.db.execute(f"PRAGMA table_info({table})")).fetchall()]
                cols = [c for c in src_cols if c in dst_cols]
                if not cols:
                    continue
                rows = src.execute(f"SELECT {','.join(cols)} FROM {table}").fetchall()
                if not rows:
                    continue
                placeholders = ",".join("?" for _ in cols)
                col_sql = ",".join(cols)
                # Replace is intentional for the bot's operational data; web login tables are never imported.
                await bot.db.executemany(f"INSERT OR REPLACE INTO {table} ({col_sql}) VALUES ({placeholders})", [tuple(r[c] for c in cols) for r in rows])
                imported += len(rows)
            await bot.db.commit()
            src.close()
            g = guild()
            if g:
                await bot.refresh_panels(g)
            return RedirectResponse(f"/settings?ok={imported}+Datensätze+importiert", status_code=303)
        except Exception as exc:
            print("DB import failed:", repr(exc))
            return RedirectResponse("/settings?error=Import+fehlgeschlagen", status_code=303)
        finally:
            if tmp:
                try: os.unlink(tmp)
                except OSError: pass

    @app.post("/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        await ensure_owner()
        cur = await bot.db.execute("SELECT * FROM web_users WHERE username=?", (username.strip().lower(),))
        user = await cur.fetchone()
        if not user or not _check_password(password, user["password_hash"]):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Benutzername oder Passwort ist falsch."}, status_code=401)
        token = secrets.token_urlsafe(32)
        await bot.db.execute("INSERT INTO web_sessions(token,user_id,expires_at) VALUES(?,?,?)",
                             (token, user["id"], (datetime.utcnow() + timedelta(hours=24)).replace(microsecond=0).isoformat()))
        await bot.db.execute("DELETE FROM web_sessions WHERE user_id=? AND token<>?", (user["id"], token))
        await bot.db.commit()
        target = "/tutorial" if not bool(user["onboarding_seen"]) else ("/servers" if user["role"] == "owner" and len(bot.guilds) > 1 else "/dashboard")
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie("clubbot_session", token, httponly=True, samesite="lax", secure=False, max_age=86400)
        return resp

    @app.post("/logout")
    async def logout(request: Request):
        sid = request.cookies.get("clubbot_session")
        if bot.db and sid:
            await bot.db.execute("DELETE FROM web_sessions WHERE token=?", (sid,))
            await bot.db.commit()
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("clubbot_session")
        return resp

    @app.post("/password")
    async def change_password(request: Request, password: str = Form(...), password_confirm: str = Form(...)):
        user = await require_user(request)
        if not user:
            return RedirectResponse("/", status_code=303)
        if password != password_confirm or len(password) < 8:
            return templates.TemplateResponse("change_password.html", {"request": request, "user": user, "error": "Die Passwörter müssen übereinstimmen und mindestens 8 Zeichen haben."}, status_code=400)
        await bot.db.execute("UPDATE web_users SET password_hash=?,must_change_password=0 WHERE id=?", (_hash_password(password), user["id"]))
        await bot.db.commit()
        return RedirectResponse("/tutorial", status_code=303)

    async def allowed(request):
        return await require_user(request)

    @app.post("/aufstellung/status")
    async def attendance_status(request: Request, user_id: int = Form(...), status: str = Form(...), reason: str = Form("")):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        if status not in {"angemeldet", "abgemeldet", "offen"}:
            status = "offen"
        await bot.db.execute(
            "INSERT INTO attendance(user_id,status,reason,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,updated_at=excluded.updated_at",
            (user_id, status, reason.strip() or None, datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        g = guild()
        if g:
            await bot.refresh_panels(g, ["aufstellung", "dienst"])
        return RedirectResponse("/aufstellung", status_code=303)

    @app.post("/aufstellung/time")
    async def attendance_time(request: Request, time_value: str = Form(...)):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        g = guild()
        if g:
            await database.set_setting(bot.db, f"aufstellung_time:{g.id}", time_value.strip())
            await bot.repost_panel(g, "aufstellung")
        return RedirectResponse("/aufstellung", status_code=303)

    @app.post("/aufstellung/add")
    async def attendance_add(request: Request, user_id: int = Form(...), rank: str = Form(...), status: str = Form("offen")):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        g = guild()
        if not g:
            return RedirectResponse("/aufstellung", status_code=303)
        member = g.get_member(user_id)
        role = next((r for r in g.roles if r.name == rank), None)
        if not member or not role:
            return RedirectResponse("/aufstellung?error=Mitglied+oder+Rang+nicht+gefunden", status_code=303)
        try:
            current_rank_roles = [r for r in member.roles if r.name in set(rank_names(g))]
            if current_rank_roles:
                await member.remove_roles(*current_rank_roles, reason="Webpanel Rangwechsel")
            await member.add_roles(role, reason="Webpanel Aufstellung hinzufügen")
        except Exception as exc:
            # Do not crash the website if Discord rejects a role change (usually role hierarchy/permissions).
            print("Webpanel role change failed:", repr(exc))
            return RedirectResponse("/aufstellung?error=Discord-Rolle+konnte+nicht+gesetzt+werden.+Prüfe+Bot-Rollenposition+und+Berechtigungen.", status_code=303)
        await bot.db.execute(
            "INSERT INTO attendance(user_id,status,reason,updated_at) VALUES(?,?,NULL,?) "
            "ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,reason=NULL,updated_at=excluded.updated_at",
            (user_id, status if status in {"angemeldet", "abgemeldet", "offen"} else "offen", datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        await bot.refresh_panels(g, ["mitarbeiter", "memberliste", "rang", "aufstellung", "dienst"])
        return RedirectResponse("/aufstellung?ok=Mitglied+gespeichert", status_code=303)

    @app.post("/members/rank")
    async def member_rank(request: Request, user_id: int = Form(...), rank: str = Form(...)):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        g = guild()
        if not g:
            return RedirectResponse("/members", status_code=303)
        member = g.get_member(user_id)
        if member:
            names = set(rank_names(g))
            current = [r for r in member.roles if r.name in names]
            if current:
                await member.remove_roles(*current, reason="Webpanel Rangwechsel")
            if rank:
                role = next((r for r in g.roles if r.name == rank), None)
                if role:
                    await member.add_roles(role, reason="Webpanel Rangwechsel")
            await bot.refresh_panels(g, ["mitarbeiter", "memberliste", "rang", "aufstellung", "dienst"])
        return RedirectResponse("/members", status_code=303)

    @app.post("/aufstellung/schedule")
    async def attendance_schedule(request: Request, send_time: str = Form("17:00"), days: list[str] = Form([]), reset_on_send: str = Form("0")):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        g = guild()
        if g:
            clean_days = [d for d in days if d in {"0","1","2","3","4","5","6"}]
            await database.set_setting(bot.db, f"aufstellung_send_time:{g.id}", send_time.strip() or "17:00")
            await database.set_setting(bot.db, f"aufstellung_send_days:{g.id}", ",".join(clean_days))
            await database.set_setting(bot.db, f"aufstellung_reset_on_send:{g.id}", "1" if reset_on_send == "1" else "0")
        return RedirectResponse("/aufstellung?ok=Zeitplan+gespeichert", status_code=303)

    @app.post("/aufstellung/design")
    async def attendance_design(request: Request, title: str = Form("Aufstellung"), description: str = Form(""), ping: str = Form("Ophelia"), footer: str = Form(""), color: str = Form("#2B2D31"), layout: str = Form("embed")):
        if not await allowed(request):
            return RedirectResponse("/", status_code=303)
        g = guild()
        if g:
            if layout not in {"embed","compact","table"}: layout = "embed"
            for key, value in {"title":title, "description":description, "ping":ping, "footer":footer, "color":color, "layout":layout}.items():
                await database.set_setting(bot.db, f"aufstellung_{key}:{g.id}", value.strip())
            await bot.repost_panel(g, "aufstellung")
        return RedirectResponse("/aufstellung?ok=Design+gespeichert", status_code=303)

    @app.post("/aufstellung/send-now")
    async def attendance_send_now(request: Request):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        g = guild()
        if g: await bot.repost_panel(g, "aufstellung")
        return RedirectResponse("/aufstellung?ok=Panel+neu+gesendet", status_code=303)

    @app.post("/aufstellung/button")
    async def update_button(request: Request, button_key: str = Form(...), label: str = Form(...), style: str = Form(...), enabled: str = Form("0")):
        user = await require_user(request)
        if not user:
            return RedirectResponse("/", status_code=303)
        if button_key not in {"anmelden", "abmelden", "refresh", "shift"}:
            return RedirectResponse("/aufstellung", status_code=303)
        if style not in {"success", "danger", "secondary", "primary"}:
            style = "secondary"
        on = 1 if enabled == "1" else 0
        await bot.db.execute("UPDATE web_panel_buttons SET label=?,style=?,enabled=? WHERE panel_key='aufstellung' AND button_key=?",
                             (label.strip()[:80] or button_key.title(), style, on, button_key))
        await bot.db.commit()
        if hasattr(bot, "load_web_button_config"):
            await bot.load_web_button_config()
        g = guild()
        if g:
            await bot.repost_panel(g, "aufstellung")
        return RedirectResponse("/aufstellung", status_code=303)

    @app.post("/settings")
    async def save_settings(request: Request, ranks: str = Form(""), leaders: str = Form(""), officers: str = Form(""), areas: str = Form("")):
        user = await require_user(request)
        if not user or user["role"] != "owner":
            return RedirectResponse("/dashboard", status_code=303)
        for key, value in [("web_ranks", ranks), ("web_leaders", leaders), ("web_officers", officers), ("web_areas", areas)]:
            await database.set_setting(bot.db, key, value.strip())
        await apply_saved_roles()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["mitarbeiter", "rang", "memberliste", "dienst", "aufstellung"])
        return RedirectResponse("/ranks", status_code=303)

    @app.post("/info")
    async def add_info(request: Request, title: str = Form(...), body: str = Form(...)):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await bot.db.execute("INSERT INTO infos(title,body,updated_at) VALUES(?,?,?)", (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M")))
        await bot.db.commit()
        for g in bot.guilds: await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/info/delete")
    async def del_info(request: Request, info_id: int = Form(...)):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await bot.db.execute("DELETE FROM infos WHERE id=?", (info_id,)); await bot.db.commit()
        for g in bot.guilds: await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/info/edit")
    async def edit_info(request: Request, info_id: int = Form(...), title: str = Form(...), body: str = Form(...)):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await bot.db.execute("UPDATE infos SET title=?,body=?,updated_at=? WHERE id=?", (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M"), info_id)); await bot.db.commit()
        for g in bot.guilds: await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/katalog")
    async def add_katalog(request: Request, name: str = Form(...), description: str = Form(...)):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await bot.db.execute("INSERT INTO catalog(name,description) VALUES(?,?)", (name.strip(), description.strip())); await bot.db.commit()
        for g in bot.guilds: await bot.refresh_panels(g, ["katalog"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/regeln")
    async def save_regeln(request: Request, rules: str = Form("")):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await database.set_setting(bot.db, "regeln", rules.strip())
        for g in bot.guilds: await bot.refresh_panels(g, ["regeln"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/status")
    async def save_status(request: Request, club_status: str = Form("geschlossen"), status_text: str = Form("")):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await database.set_setting(bot.db, "club_status", club_status.strip())
        await database.set_setting(bot.db, "club_status_text", status_text.strip())
        for g in bot.guilds: await bot.refresh_panels(g, ["status"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/notiz")
    async def add_note(request: Request, title: str = Form(...), body: str = Form(...)):
        if not await allowed(request): return RedirectResponse("/", status_code=303)
        await bot.db.execute("INSERT INTO notes(title,body,created_at) VALUES(?,?,?)", (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M"))); await bot.db.commit()
        for g in bot.guilds: await bot.refresh_panels(g, ["notizen"])
        return RedirectResponse("/content", status_code=303)

    @app.post("/users/create")
    async def create_user(request: Request, name: str = Form(...), username_input: str = Form(""), password_input: str = Form("")):
        user = await require_user(request)
        if not user or user["role"] != "owner": return RedirectResponse("/dashboard", status_code=303)
        clean = "".join(ch.lower() for ch in name.strip() if ch.isalnum() or ch in " ._- ").strip()
        parts = clean.replace("_", " ").replace("-", " ").split()
        requested = "".join(ch.lower() for ch in username_input.strip() if ch.isalnum() or ch in "._-")[:32]
        base = requested or ((parts[0] + ("." + parts[-1][0] if len(parts) > 1 else ""))[:24] or "user")
        username, i = base, 2
        while True:
            cur = await bot.db.execute("SELECT 1 FROM web_users WHERE username=?", (username,))
            if not await cur.fetchone(): break
            if requested:
                return RedirectResponse("/users?error=Benutzername+bereits+vergeben", status_code=303)
            username = f"{base}{i}"; i += 1
        password = password_input.strip() or _new_password()
        if len(password) < 8:
            return RedirectResponse("/users?error=Passwort+mindestens+8+Zeichen", status_code=303)
        must_change = 0 if password_input.strip() else 1
        await bot.db.execute("INSERT INTO web_users(username,password_hash,role,must_change_password) VALUES(?,?,?,?)", (username, _hash_password(password), "user", must_change)); await bot.db.commit()
        return templates.TemplateResponse("credentials.html", {"request": request, "username": username, "password": password})

    @app.post("/users/delete")
    async def delete_user(request: Request, user_id: int = Form(...)):
        user = await require_user(request)
        if not user or user["role"] != "owner" or user_id == user["id"]: return RedirectResponse("/users", status_code=303)
        await bot.db.execute("DELETE FROM web_users WHERE id=? AND role!='owner'", (user_id,)); await bot.db.commit()
        return RedirectResponse("/users", status_code=303)

    @app.post("/users/reset")
    async def reset_user(request: Request, user_id: int = Form(...)):
        user = await require_user(request)
        if not user or user["role"] != "owner": return RedirectResponse("/users", status_code=303)
        password = _new_password()
        await bot.db.execute("UPDATE web_users SET password_hash=?,must_change_password=1 WHERE id=? AND role!='owner'", (_hash_password(password), user_id)); await bot.db.commit()
        cur = await bot.db.execute("SELECT username FROM web_users WHERE id=?", (user_id,)); target = await cur.fetchone()
        return templates.TemplateResponse("credentials.html", {"request": request, "username": target["username"] if target else "", "password": password})

    @app.post("/builder/update")
    async def builder_update(request: Request):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        f = await request.form()
        panel_id = int(f.get("panel_id"))
        cur = await bot.db.execute("SELECT * FROM web_builder_panels WHERE id=?", (panel_id,)); existing = await cur.fetchone()
        if not existing: return RedirectResponse("/panels", status_code=303)
        values = (
            str(f.get("label", existing["label"])).strip(), str(f.get("title_override", "")).strip(),
            str(f.get("description_override", "")).strip(), str(f.get("color_hex", "#5865F2")).strip() or "#5865F2",
            str(f.get("footer_text", "")).strip(), str(f.get("message_type", existing["message_type"] or "embed")),
            str(f.get("content_text", "")).strip(), str(f.get("image_url", "")).strip(), str(f.get("thumbnail_url", "")).strip(),
            str(f.get("layout", existing["layout"] or "embed")), 1 if f.get("auto_send") else 0,
            str(f.get("schedule_time", "")).strip(), ",".join(f.getlist("schedule_days")),
            int(f.get("schedule_channel_id")) if str(f.get("schedule_channel_id", "")).isdigit() else None, panel_id
        )
        await bot.db.execute("""UPDATE web_builder_panels SET label=?,title_override=?,description_override=?,color_hex=?,footer_text=?,
            message_type=?,content_text=?,image_url=?,thumbnail_url=?,layout=?,auto_send=?,schedule_time=?,schedule_days=?,schedule_channel_id=? WHERE id=?""", values)
        await bot.db.commit()
        if existing["source"] == "bot":
            for g in bot.guilds: await bot.refresh_panels(g, [existing["panel_key"]])
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/upload")
    async def builder_upload(request: Request, panel_id: int = Form(...), kind: str = Form("image"), image: UploadFile = File(...)):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        cur = await bot.db.execute("SELECT panel_key FROM web_builder_panels WHERE id=?", (panel_id,)); row = await cur.fetchone()
        if not row: return RedirectResponse("/panels", status_code=303)
        suffix = Path(image.filename or "image.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}: return RedirectResponse("/panels", status_code=303)
        data = await image.read()
        if not data or len(data) > 8 * 1024 * 1024: return RedirectResponse("/panels", status_code=303)
        safe_kind = "thumbnail" if kind == "thumbnail" else "image"
        name = f"{row['panel_key']}-{safe_kind}-{secrets.token_hex(6)}{suffix}"
        target = UPLOADS / name
        target.write_bytes(data)
        rel = f"data/uploads/{name}"
        column = "thumbnail_path" if safe_kind == "thumbnail" else "image_path"
        await bot.db.execute(f"UPDATE web_builder_panels SET {column}=? WHERE id=?", (rel, panel_id)); await bot.db.commit()
        return RedirectResponse(f"/panels#panel-{panel_id}", status_code=303)

    @app.post("/builder/field/add")
    async def builder_field_add(request: Request, panel_key: str = Form(...), name: str = Form(...), value: str = Form(""), inline: str = Form("")):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        cur = await bot.db.execute("SELECT COALESCE(MAX(sort_order),0)+1 n FROM web_setup_fields WHERE panel_key=?", (panel_key,)); n=(await cur.fetchone())["n"]
        await bot.db.execute("INSERT INTO web_setup_fields(panel_key,name,value,inline,sort_order) VALUES(?,?,?,?,?)", (panel_key,name.strip(),value.strip(),1 if inline else 0,n)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/field/delete")
    async def builder_field_delete(request: Request, field_id: int = Form(...)):
        user = await require_user(request)
        if user: await bot.db.execute("DELETE FROM web_setup_fields WHERE id=?", (field_id,)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/action/add")
    async def builder_action_add(request: Request, panel_key: str = Form(...), label: str = Form(...), style: str = Form("secondary"), action_type: str = Form("url"), action_value: str = Form("")):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        cur = await bot.db.execute("SELECT COALESCE(MAX(sort_order),0)+1 n FROM web_setup_actions WHERE panel_key=?", (panel_key,)); n=(await cur.fetchone())["n"]
        await bot.db.execute("INSERT INTO web_setup_actions(panel_key,label,style,action_type,action_value,sort_order) VALUES(?,?,?,?,?,?)", (panel_key,label.strip(),style,action_type,action_value.strip(),n)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/action/delete")
    async def builder_action_delete(request: Request, action_id: int = Form(...)):
        user = await require_user(request)
        if user: await bot.db.execute("DELETE FROM web_setup_actions WHERE id=?", (action_id,)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)


    @app.post("/builder/button/update")
    async def builder_button_update(request: Request):
        user = await require_user(request)
        if not user:
            return RedirectResponse("/", status_code=303)
        f = await request.form()
        panel_key = str(f.get("panel_key", ""))
        button_key = str(f.get("button_key", ""))
        label = str(f.get("label", "")).strip()
        style = str(f.get("style", "secondary"))
        enabled = 1 if f.get("enabled") else 0
        if style not in {"primary", "secondary", "success", "danger"}: style = "secondary"
        await bot.db.execute(
            "UPDATE web_panel_buttons SET label=?,style=?,enabled=? WHERE panel_key=? AND button_key=?",
            (label or "Button", style, enabled, panel_key, button_key),
        )
        await bot.db.commit()
        await bot.load_web_button_config()
        g = guild()
        if g:
            await bot.refresh_panels(g, [panel_key])
        return RedirectResponse(f"/panels#panel-{panel_key}", status_code=303)

    @app.post("/builder/reset-overrides")
    async def builder_reset_overrides(request: Request, panel_id: int = Form(...)):
        user = await require_user(request)
        if not user:
            return RedirectResponse("/", status_code=303)
        cur = await bot.db.execute("SELECT panel_key FROM web_builder_panels WHERE id=?", (panel_id,))
        row = await cur.fetchone()
        if row:
            await bot.db.execute("UPDATE web_builder_panels SET title_override='',description_override='',footer_text='' WHERE id=?", (panel_id,))
            await bot.db.commit()
            g = guild()
            if g:
                await bot.refresh_panels(g, [row["panel_key"]])
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/create")
    async def builder_create(request: Request, label: str = Form(...), title: str = Form(...), description: str = Form(""), color_hex: str = Form("#5865F2"), footer_text: str = Form("")):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        base = "custom-" + "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip()).strip("-")
        base = base[:40] or "custom-panel"; key, i = base, 2
        while True:
            cur = await bot.db.execute("SELECT 1 FROM web_builder_panels WHERE panel_key=?", (key,))
            if not await cur.fetchone(): break
            key = f"{base}-{i}"; i += 1
        cur = await bot.db.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM web_builder_panels"); order = (await cur.fetchone())["n"]
        await bot.db.execute("INSERT INTO web_builder_panels(panel_key,label,title_override,description_override,source,color_hex,footer_text,sort_order) VALUES(?,?,?,?, 'custom', ?,?,?)", (key, label.strip(), title.strip(), description.strip(), color_hex.strip() or "#5865F2", footer_text.strip(), order)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/delete")
    async def builder_delete(request: Request, panel_id: int = Form(...)):
        user = await require_user(request)
        if not user: return RedirectResponse("/", status_code=303)
        await bot.db.execute("DELETE FROM web_builder_panels WHERE id=? AND source='custom'", (panel_id,)); await bot.db.commit()
        return RedirectResponse("/panels", status_code=303)

    @app.post("/builder/publish")
    async def builder_publish(request: Request, panel_id: int = Form(...), channel_id: int = Form(...)):
        user = await require_user(request)
        if not user or not bot.guilds: return RedirectResponse("/panels", status_code=303)
        g = guild(); channel = g.get_channel(channel_id)
        if not channel: return RedirectResponse("/panels", status_code=303)
        cur = await bot.db.execute("SELECT panel_key,source FROM web_builder_panels WHERE id=?", (panel_id,)); row = await cur.fetchone()
        if row:
            await (bot.post_custom_panel(channel, row["panel_key"]) if row["source"] == "custom" else bot.post_panel(channel, row["panel_key"]))
        return RedirectResponse("/panels", status_code=303)

    return app
