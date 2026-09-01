# ClubBot – Discord-Listen + Website, 24/7

Der Bot läuft **nicht auf deinem PC**. Er läuft auf einem Hoster im Internet.
Wenn dein Rechner aus ist, bleibt der Bot trotzdem online.

Es gibt:

- Live-Listen in Discord (wie die Mitarbeiterliste)
- Buttons unter den Listen
- Eine Website, auf der Leitung Infos / Lager / Katalog einträgt
- Alles wird in einer Datenbank gespeichert

Ausweis-Fotos werden **nicht** gespeichert.

## 1. Discord vorbereiten

1. Gehe zu https://discord.com/developers/applications
2. Neue Application anlegen
3. Links auf **Bot**
   - Bot erstellen
   - Token kopieren
   - Privileged Gateway Intents: **SERVER MEMBERS INTENT** einschalten
4. Links auf **OAuth2 → URL Generator**
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: Manage Roles, Manage Channels, Send Messages, Embed Links, Read Message History, Use Slash Commands, View Channels
5. Den Link öffnen und den Bot auf den Server einladen
6. Die Bot-Rolle in Discord **über** die Rang-Rollen schieben (sonst kann er nicht befördern)

Rang-Rollen müssen **genau so** heißen:

- Geschäftsleitung
- Clubleitung
- Leitende Servicekraft
- Servicekraft
- Junior-Servicekraft
- Auszubildende/r

## 2. Lokal testen (optional)

```bash
cd clubbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env ausfüllen: DISCORD_TOKEN und WEB_PASSWORD
python bot/main.py
```

Website dann: http://localhost:8080

## 3. Dauerhaft hosten (PC aus = Bot bleibt an)

Am einfachsten mit Railway oder Render.

### Railway

1. Account auf https://railway.app
2. New Project → Deploy from GitHub **oder** leeres Projekt + Dockerfile
3. Diese Ordner hochladen
4. Variables setzen:
   - `DISCORD_TOKEN`
   - `WEB_PASSWORD`
   - `WEB_PORT=8080`
5. Public Domain für die Website erzeugen

### Render

1. https://render.com → New Web Service
2. Dockerfile verwenden
3. Dieselben Variablen setzen
4. Instanz auf „always on“ lassen (Free-Tarif schläft oft ein – dann lieber 7 $/Monat Starter)

### Eigenes Linux / VPS

```bash
docker compose up -d --build
```

`restart: always` startet den Bot nach jedem Absturz oder Server-Neustart neu.

## 4. Auf dem Discord einrichten

In den gewünschten Kanälen nacheinander:

- `/setup panel:mitarbeiter`
- `/setup panel:memberliste`
- `/setup panel:rang`
- `/setup panel:aufstellung`
- `/setup panel:dienst`
- `/setup panel:katalog`
- `/setup panel:sanktionen`
- `/setup panel:ausruestung`
- `/setup panel:lager`
- `/setup panel:urlaub`
- `/setup panel:infos`
- `/setup panel:arbeiter`
- `/logkanal kanal:#logs`

Die Nachricht bleibt stehen und **aktualisiert sich selbst**.

## 5. Was die Website kann

Login mit `WEB_PASSWORD`.

Dort eintragen:

- Infos (stehen danach in der Discord-Liste „Infos“)
- Lager-Bestand
- Sanktionskatalog-Punkte

Änderungen auf der Website schreiben sofort die Discord-Nachricht um.

## 6. Wichtige Slash-Commands (nur Setup / Leitung)

| Command | Zweck |
|---|---|
| `/setup` | Liste in den aktuellen Kanal setzen |
| `/logkanal` | Log-Kanal |
| `/befoerdern` | Rang-Rolle setzen |
| `/degradieren` | Rang-Rolle setzen |
| `/urlaub_status` | Antrag genehmigen / ablehnen |
| `/sanktion_aufheben` | Sanktion beenden |
| `/arbeiter_setzen` | Name/Telefon/geprüft (kein Foto) |
| `/arbeiter_entfernen` | Arbeiter austragen |

Alltag läuft über **Buttons**, nicht über Commands.
