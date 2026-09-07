import os
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


def _lines(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def make_app(bot):
    app = FastAPI()
    templates = Jinja2Templates(directory=str(TEMPLATES))
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def logged_in(request: Request) -> bool:
        return request.cookies.get("clubbot") == os.getenv("WEB_PASSWORD", "")

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

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if not logged_in(request):
            return templates.TemplateResponse("login.html", {"request": request, "error": ""})
        db = bot.db
        infos, lager, catalog, eq = [], [], [], []
        ranks = leaders = officers = areas = rules = status_text = club_status = ""
        notes = []
        if db:
            cur = await db.execute("SELECT id, title, body, updated_at FROM infos ORDER BY id DESC")
            infos = await cur.fetchall()
            cur = await db.execute("SELECT item, category, qty FROM inventory ORDER BY category, item")
            lager = await cur.fetchall()
            cur = await db.execute("SELECT id, name, description FROM catalog ORDER BY id")
            catalog = await cur.fetchall()
            cur = await db.execute("SELECT id, name FROM equipment_items ORDER BY id")
            eq = await cur.fetchall()
            ranks = await database.get_setting(db, "web_ranks", "") or ""
            leaders = await database.get_setting(db, "web_leaders", "") or ""
            officers = await database.get_setting(db, "web_officers", "") or ""
            areas = await database.get_setting(db, "web_areas", "Bar\nTür\nService\nBüro\nNicht eingeteilt") or ""
            rules = await database.get_setting(db, "regeln", "") or ""
            status_text = await database.get_setting(db, "club_status_text", "") or ""
            club_status = await database.get_setting(db, "club_status", "geschlossen") or "geschlossen"
            cur = await db.execute("SELECT id, title, body, created_at FROM notes ORDER BY id DESC")
            notes = await cur.fetchall()
        guild_name = bot.guilds[0].name if bot.guilds else "noch nicht verbunden"
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "infos": infos,
                "lager": lager,
                "catalog": catalog,
                "eq": eq,
                "ranks": ranks,
                "leaders": leaders,
                "officers": officers,
                "areas": areas,
                "rules": rules,
                "status_text": status_text,
                "club_status": club_status,
                "notes": notes,
                "guild_name": guild_name,
                "online": bool(bot.user),
            },
        )

    @app.post("/login")
    async def login(password: str = Form(...)):
        if password != os.getenv("WEB_PASSWORD", ""):
            return RedirectResponse("/", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("clubbot", password, httponly=True, samesite="lax")
        return resp

    @app.post("/logout")
    async def logout():
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("clubbot")
        return resp

    @app.post("/settings")
    async def save_settings(
        request: Request,
        ranks: str = Form(""),
        leaders: str = Form(""),
        officers: str = Form(""),
        areas: str = Form(""),
    ):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await database.set_setting(bot.db, "web_ranks", ranks.strip())
        await database.set_setting(bot.db, "web_leaders", leaders.strip())
        await database.set_setting(bot.db, "web_officers", officers.strip())
        await database.set_setting(bot.db, "web_areas", areas.strip())
        await apply_saved_roles()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["mitarbeiter", "rang", "memberliste", "dienst", "aufstellung"])
        return RedirectResponse("/", status_code=303)

    @app.post("/info")
    async def add_info(request: Request, title: str = Form(...), body: str = Form(...)):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute(
            "INSERT INTO infos(title, body, updated_at) VALUES(?, ?, ?)",
            (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/", status_code=303)

    @app.post("/info/delete")
    async def del_info(request: Request, info_id: int = Form(...)):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute("DELETE FROM infos WHERE id = ?", (info_id,))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["infos"])
        return RedirectResponse("/", status_code=303)

    @app.post("/lager")
    async def set_lager(
        request: Request,
        item: str = Form(...),
        category: str = Form("Sonstiges"),
        qty: int = Form(0),
    ):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute(
            "INSERT INTO inventory(item, category, qty) VALUES(?, ?, ?) ON CONFLICT(item) DO UPDATE SET category=excluded.category, qty=excluded.qty",
            (item.strip(), category.strip(), qty),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["lager"])
        return RedirectResponse("/", status_code=303)

    @app.post("/katalog")
    async def add_katalog(request: Request, name: str = Form(...), description: str = Form(...)):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute(
            "INSERT INTO catalog(name, description) VALUES(?, ?)",
            (name.strip(), description.strip()),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["katalog"])
        return RedirectResponse("/", status_code=303)

    @app.post("/regeln")
    async def save_regeln(request: Request, rules: str = Form("")):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await database.set_setting(bot.db, "regeln", rules.strip())
        for g in bot.guilds:
            await bot.refresh_panels(g, ["regeln"])
        return RedirectResponse("/", status_code=303)

    @app.post("/status")
    async def save_status(request: Request, club_status: str = Form("geschlossen"), status_text: str = Form("")):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await database.set_setting(bot.db, "club_status", club_status.strip())
        await database.set_setting(bot.db, "club_status_text", status_text.strip())
        for g in bot.guilds:
            await bot.refresh_panels(g, ["status"])
        return RedirectResponse("/", status_code=303)

    @app.post("/notiz")
    async def add_note(request: Request, title: str = Form(...), body: str = Form(...)):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute(
            "INSERT INTO notes(title, body, created_at) VALUES(?, ?, ?)",
            (title.strip(), body.strip(), datetime.now().strftime("%d.%m.%Y %H:%M")),
        )
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["notizen"])
        return RedirectResponse("/", status_code=303)

    @app.post("/ausruestung")
    async def add_eq(request: Request, name: str = Form(...)):
        if not logged_in(request) or not bot.db:
            return RedirectResponse("/", status_code=303)
        await bot.db.execute("INSERT INTO equipment_items(name) VALUES(?)", (name.strip(),))
        await bot.db.commit()
        for g in bot.guilds:
            await bot.refresh_panels(g, ["ausruestung"])
        return RedirectResponse("/", status_code=303)

    return app
