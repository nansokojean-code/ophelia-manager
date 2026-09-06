import os
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database
from ranks import set_areas, set_guild_roles

TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

SESSION_COOKIE = "ophelia_uid"
SESSION_TOKEN = "ophelia_tok"


def _lines(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _username_from_display(display_name: str) -> str:
    parts = "".join(c if c.isalnum() or c.isspace() else " " for c in display_name.lower()).split()
    if not parts:
        return "user"
    if len(parts) == 1:
        return parts[0][:16]
    return parts[0][:12]


def _temp_password() -> str:
    return f"Ophelia-{secrets.token_hex(3)}"


def make_app(bot):
    app = FastAPI()
    templates = Jinja2Templates(directory=str(TEMPLATES))
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    # session_token -> user_id (in-memory; ok for single process)
    sessions: dict[str, int] = {}

    async def current_user(request: Request):
        if not bot.db:
            return None
        uid = request.cookies.get(SESSION_COOKIE)
        tok = request.cookies.get(SESSION_TOKEN)
        if not uid or not tok:
            return None
        if sessions.get(tok) != int(uid):
            return None
        return await database.get_web_user_by_id(bot.db, int(uid))

    def set_session(resp: RedirectResponse, user_id: int):
        tok = secrets.token_urlsafe(24)
        sessions[tok] = user_id
        resp.set_cookie(SESSION_COOKIE, str(user_id), httponly=True, samesite="lax")
        resp.set_cookie(SESSION_TOKEN, tok, httponly=True, samesite="lax")
        return resp

    def clear_session(resp: RedirectResponse, request: Request = None):
        if request:
            tok = request.cookies.get(SESSION_TOKEN)
            if tok and tok in sessions:
                del sessions[tok]
        resp.delete_cookie(SESSION_COOKIE)
        resp.delete_cookie(SESSION_TOKEN)
        return resp

    async def require_user(request: Request):
        user = await current_user(request)
        if not user:
            return None, RedirectResponse("/login", status_code=303)
        if user["must_change_password"] and request.url.path != "/change-password":
            return None, RedirectResponse("/change-password", status_code=303)
        return user, None

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

    def ctx(request, user, page, **extra):
        base = {
            "request": request,
            "user": user,
            "page": page,
            "guild_name": bot.guilds[0].name if bot.guilds else "noch nicht verbunden",
            "online": bool(bot.user),
        }
        base.update(extra)
        return base

    # ---------- Auth ----------

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        user = await current_user(request)
        if user:
            if user["must_change_password"]:
                return RedirectResponse("/change-password", status_code=303)
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse("login.html", {"request": request, "error": ""})

    @app.post("/login")
    async def login(request: Request, username: str = Form(...), password: str = Form(...)):
        if not bot.db:
            return templates.TemplateResponse(
                "login.html", {"request": request, "error": "Datenbank nicht bereit."}
            )
        row = await database.get_web_user(bot.db, username)
        if not row or not database.verify_password(password, row["password_hash"]):
            return templates.TemplateResponse(
                "login.html", {"request": request, "error": "Benutzername oder Passwort falsch."}
            )
        if row["must_change_password"]:
            resp = RedirectResponse("/change-password", status_code=303)
        else:
            resp = RedirectResponse("/", status_code=303)
        return set_session(resp, row["id"])

    @app.get("/change-password", response_class=HTMLResponse)
    async def change_pw_page(request: Request):
        user = await current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse("change_password.html", {"request": request, "error": ""})

    @app.post("/change-password")
    async def change_pw(
        request: Request,
        password: str = Form(...),
        password2: str = Form(...),
    ):
        user = await current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        if len(password) < 6:
            return templates.TemplateResponse(
                "change_password.html",
                {"request": request, "error": "Mindestens 6 Zeichen."},
            )
        if password != password2:
            return templates.TemplateResponse(
                "change_password.html",
                {"request": request, "error": "Passwörter stimmen nicht überein."},
            )
        await database.set_web_password(bot.db, user["id"], password, clear_must_change=True)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        resp = RedirectResponse("/login", status_code=303)
        return clear_session(resp, request)

    # ---------- Dashboard ----------

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        db = bot.db
        catalog_count = lager_count = infos_count = notes_count = users_count = 0
        club_status = ""
        if db:
            cur = await db.execute("SELECT COUNT(*) AS c FROM catalog")
            catalog_count = (await cur.fetchone())["c"]
            cur = await db.execute("SELECT COUNT(*) AS c FROM inventory")
            lager_count = (await cur.fetchone())["c"]
            cur = await db.execute("SELECT COUNT(*) AS c FROM infos")
            infos_count = (await cur.fetchone())["c"]
            cur = await db.execute("SELECT COUNT(*) AS c FROM notes")
            notes_count = (await cur.fetchone())["c"]
            cur = await db.execute("SELECT COUNT(*) AS c FROM web_users")
            users_count = (await cur.fetchone())["c"]
            club_status = await database.get_setting(db, "club_status", "geschlossen") or "geschlossen"
        return templates.TemplateResponse(
            "dashboard.html",
            ctx(
                request,
                user,
                "dashboard",
                catalog_count=catalog_count,
                lager_count=lager_count,
                infos_count=infos_count,
                notes_count=notes_count,
                users_count=users_count,
                club_status=club_status,
            ),
        )

    # ---------- Katalog ----------

    @app.get("/katalog", response_class=HTMLResponse)
    async def katalog_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        cur = await bot.db.execute("SELECT id, name, description FROM catalog ORDER BY id")
        catalog = await cur.fetchall()
        return templates.TemplateResponse(
            "page_katalog.html", ctx(request, user, "katalog", catalog=catalog)
        )

    @app.post("/katalog")
    async def katalog_add(request: Request, name: str = Form(...), description: str = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute(
            "INSERT INTO catalog(name, description) VALUES(?, ?)",
            (name.strip(), description.strip()),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["katalog"])
        return RedirectResponse("/katalog", status_code=303)

    @app.post("/katalog/delete")
    async def katalog_del(request: Request, item_id: int = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("DELETE FROM catalog WHERE id = ?", (item_id,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["katalog"])
        return RedirectResponse("/katalog", status_code=303)

    # ---------- Infos ----------

    @app.get("/infos", response_class=HTMLResponse)
    async def infos_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        cur = await bot.db.execute("SELECT id, title, body, updated_at FROM infos ORDER BY id DESC")
        infos = await cur.fetchall()
        return templates.TemplateResponse(
            "page_infos.html", ctx(request, user, "infos", infos=infos)
        )

    @app.post("/infos")
    async def infos_add(request: Request, title: str = Form(...), body: str = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute(
            "INSERT INTO infos(title, body, updated_at) VALUES(?, ?, ?)",
            (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/infos", status_code=303)

    @app.post("/infos/delete")
    async def infos_del(request: Request, info_id: int = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("DELETE FROM infos WHERE id = ?", (info_id,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/infos", status_code=303)

    # ---------- Lager ----------

    @app.get("/lager", response_class=HTMLResponse)
    async def lager_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        cur = await bot.db.execute("SELECT item, category, qty FROM inventory ORDER BY category, item")
        lager = await cur.fetchall()
        return templates.TemplateResponse(
            "page_lager.html", ctx(request, user, "lager", lager=lager)
        )

    @app.post("/lager")
    async def lager_set(
        request: Request,
        item: str = Form(...),
        category: str = Form("Sonstiges"),
        qty: int = Form(0),
    ):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute(
            "INSERT INTO inventory(item, category, qty) VALUES(?, ?, ?) "
            "ON CONFLICT(item) DO UPDATE SET category=excluded.category, qty=excluded.qty",
            (item.strip(), category.strip(), qty),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["lager"])
        return RedirectResponse("/lager", status_code=303)

    @app.post("/lager/delete")
    async def lager_del(request: Request, item: str = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("DELETE FROM inventory WHERE item = ?", (item,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["lager"])
        return RedirectResponse("/lager", status_code=303)

    # ---------- Rollen ----------

    @app.get("/rollen", response_class=HTMLResponse)
    async def rollen_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        ranks = await database.get_setting(bot.db, "web_ranks", "") or ""
        leaders = await database.get_setting(bot.db, "web_leaders", "") or ""
        officers = await database.get_setting(bot.db, "web_officers", "") or ""
        areas = await database.get_setting(bot.db, "web_areas", "Bar\nTür\nService\nBüro\nNicht eingeteilt") or ""
        return templates.TemplateResponse(
            "page_rollen.html",
            ctx(request, user, "rollen", ranks=ranks, leaders=leaders, officers=officers, areas=areas),
        )

    @app.post("/rollen")
    async def rollen_save(
        request: Request,
        ranks: str = Form(""),
        leaders: str = Form(""),
        officers: str = Form(""),
        areas: str = Form(""),
    ):
        user, redir = await require_user(request)
        if redir:
            return redir
        await database.set_setting(bot.db, "web_ranks", ranks.strip())
        await database.set_setting(bot.db, "web_leaders", leaders.strip())
        await database.set_setting(bot.db, "web_officers", officers.strip())
        await database.set_setting(bot.db, "web_areas", areas.strip())
        await apply_saved_roles()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["mitarbeiter", "rang", "memberliste", "dienst", "aufstellung"])
        return RedirectResponse("/rollen", status_code=303)

    # ---------- Regeln ----------

    @app.get("/regeln", response_class=HTMLResponse)
    async def regeln_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        rules = await database.get_setting(bot.db, "regeln", "") or ""
        return templates.TemplateResponse(
            "page_regeln.html", ctx(request, user, "regeln", rules=rules)
        )

    @app.post("/regeln")
    async def regeln_save(request: Request, rules: str = Form("")):
        user, redir = await require_user(request)
        if redir:
            return redir
        await database.set_setting(bot.db, "regeln", rules.strip())
        for g in bot.guilds:
            await bot.refresh_panels(g, ["regeln"])
        return RedirectResponse("/regeln", status_code=303)

    # ---------- Status ----------

    @app.get("/status", response_class=HTMLResponse)
    async def status_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        club_status = await database.get_setting(bot.db, "club_status", "geschlossen") or "geschlossen"
        status_text = await database.get_setting(bot.db, "club_status_text", "") or ""
        return templates.TemplateResponse(
            "page_status.html",
            ctx(request, user, "status", club_status=club_status, status_text=status_text),
        )

    @app.post("/status")
    async def status_save(
        request: Request,
        club_status: str = Form("geschlossen"),
        status_text: str = Form(""),
    ):
        user, redir = await require_user(request)
        if redir:
            return redir
        await database.set_setting(bot.db, "club_status", club_status.strip())
        await database.set_setting(bot.db, "club_status_text", status_text.strip())
        for g in bot.guilds:
            await bot.refresh_panels(g, ["status"])
        return RedirectResponse("/status", status_code=303)

    # ---------- Notizen ----------

    @app.get("/notizen", response_class=HTMLResponse)
    async def notizen_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        cur = await bot.db.execute("SELECT id, title, body, created_at FROM notes ORDER BY id DESC")
        notes = await cur.fetchall()
        return templates.TemplateResponse(
            "page_notizen.html", ctx(request, user, "notizen", notes=notes)
        )

    @app.post("/notizen")
    async def notizen_add(request: Request, title: str = Form(...), body: str = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute(
            "INSERT INTO notes(title, body, created_at) VALUES(?, ?, ?)",
            (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["notizen"])
        return RedirectResponse("/notizen", status_code=303)

    @app.post("/notizen/delete")
    async def notizen_del(request: Request, note_id: int = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["notizen"])
        return RedirectResponse("/notizen", status_code=303)

    # ---------- Ausrüstung ----------

    @app.get("/ausruestung", response_class=HTMLResponse)
    async def eq_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        cur = await bot.db.execute("SELECT id, name FROM equipment_items ORDER BY id")
        eq = await cur.fetchall()
        return templates.TemplateResponse(
            "page_ausruestung.html", ctx(request, user, "ausruestung", eq=eq)
        )

    @app.post("/ausruestung")
    async def eq_add(request: Request, name: str = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("INSERT INTO equipment_items(name) VALUES(?)", (name.strip(),))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["ausruestung"])
        return RedirectResponse("/ausruestung", status_code=303)

    @app.post("/ausruestung/delete")
    async def eq_del(request: Request, item_id: int = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        await bot.db.execute("DELETE FROM equipment_items WHERE id = ?", (item_id,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["ausruestung"])
        return RedirectResponse("/ausruestung", status_code=303)

    # ---------- Users (Owner only) ----------

    @app.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request):
        user, redir = await require_user(request)
        if redir:
            return redir
        if not user["is_owner"]:
            return RedirectResponse("/", status_code=303)
        users = await database.list_web_users(bot.db)
        return templates.TemplateResponse(
            "page_users.html",
            ctx(request, user, "users", users=users, new_creds=None),
        )

    @app.post("/users")
    async def users_create(
        request: Request,
        display_name: str = Form(...),
        username: str = Form(""),
    ):
        user, redir = await require_user(request)
        if redir:
            return redir
        if not user["is_owner"]:
            return RedirectResponse("/", status_code=303)

        uname = (username or "").strip().lower() or _username_from_display(display_name)
        uname = "".join(c for c in uname if c.isalnum() or c in "._-")[:20] or "user"
        base = uname
        n = 1
        while await database.get_web_user(bot.db, uname):
            n += 1
            uname = f"{base}{n}"

        temp_pw = _temp_password()
        await database.create_web_user(
            bot.db, uname, display_name.strip(), temp_pw, is_owner=False, must_change=True
        )
        users = await database.list_web_users(bot.db)
        return templates.TemplateResponse(
            "page_users.html",
            ctx(
                request,
                user,
                "users",
                users=users,
                new_creds={"username": uname, "password": temp_pw},
            ),
        )

    @app.post("/users/delete")
    async def users_delete(request: Request, user_id: int = Form(...)):
        user, redir = await require_user(request)
        if redir:
            return redir
        if not user["is_owner"]:
            return RedirectResponse("/", status_code=303)
        await database.delete_web_user(bot.db, user_id)
        return RedirectResponse("/users", status_code=303)

    return app
