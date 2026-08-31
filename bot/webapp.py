import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

TEMPLATES = Path(__file__).resolve().parent.parent / "web" / "templates"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def make_app(bot):
    app = FastAPI()
    templates = Jinja2Templates(directory=str(TEMPLATES))
    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def logged_in(request: Request) -> bool:
        return request.cookies.get("clubbot") == os.getenv("WEB_PASSWORD", "")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if not logged_in(request):
            return templates.TemplateResponse("login.html", {"request": request, "error": ""})
        db = bot.db
        infos = []
        lager = []
        catalog = []
        if db:
            cur = await db.execute("SELECT id, title, body, updated_at FROM infos ORDER BY id DESC")
            infos = await cur.fetchall()
            cur = await db.execute("SELECT item, category, qty FROM inventory ORDER BY category, item")
            lager = await cur.fetchall()
            cur = await db.execute("SELECT id, name, description FROM catalog ORDER BY id")
            catalog = await cur.fetchall()
        guild_name = bot.guilds[0].name if bot.guilds else "noch nicht verbunden"
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "infos": infos,
                "lager": lager,
                "catalog": catalog,
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

    return app
