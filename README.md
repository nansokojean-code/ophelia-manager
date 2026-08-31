<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ophelia Manager</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header>
    <h1>Ophelia Manager</h1>
    <p>{{ guild_name }} • Bot {% if online %}online{% else %}offline{% endif %}</p>
    <p>Alles hier eintragen. Namen müssen <strong>genau so</strong> heißen wie die Discord-Rollen.</p>
    <form method="post" action="/logout"><button class="ghost">Logout</button></form>
  </header>

  <section>
    <h2>1. Eure Rollen</h2>
    <p>Eine Rolle pro Zeile. Oben = höchster Rang.</p>
    <form method="post" action="/settings">
      <label>Rang-Rollen (Mitarbeiterliste)</label>
      <textarea name="ranks" placeholder="Owner&#10;Manager&#10;Member">{{ ranks }}</textarea>
      <label>Leitung (darf Ränge / Setup)</label>
      <textarea name="leaders" placeholder="Owner">{{ leaders }}</textarea>
      <label>Team (darf Sanktionen, Aufstellung)</label>
      <textarea name="officers" placeholder="Owner&#10;Manager">{{ officers }}</textarea>
      <label>Aufstellung-Bereiche</label>
      <textarea name="areas" placeholder="Bar&#10;Tür&#10;Service">{{ areas }}</textarea>
      <button type="submit">Rollen &amp; Bereiche speichern</button>
    </form>
  </section>

  <section>
    <h2>2. Regeln</h2>
    <form method="post" action="/regeln">
      <textarea name="rules" placeholder="Regeln hier reinschreiben">{{ rules }}</textarea>
      <button type="submit">Regeln speichern</button>
    </form>
  </section>

  <section>
    <h2>3. Club offen / geschlossen</h2>
    <form method="post" action="/status">
      <input name="club_status" value="{{ club_status }}" placeholder="offen oder geschlossen" />
      <textarea name="status_text" placeholder="z.B. Heute ab 20 Uhr">{{ status_text }}</textarea>
      <button type="submit">Status speichern</button>
    </form>
  </section>

  <section>
    <h2>4. Notizen</h2>
    <form method="post" action="/notiz">
      <input name="title" placeholder="Titel" required />
      <textarea name="body" placeholder="Notiz" required></textarea>
      <button type="submit">Notiz speichern</button>
    </form>
    <div class="list">
      {% for n in notes %}
      <article>
        <h3>{{ n["title"] }}</h3>
        <p>{{ n["body"] }}</p>
        <small>{{ n["created_at"] }}</small>
      </article>
      {% endfor %}
    </div>
  </section>

  <section>
    <h2>5. Infos für Discord</h2>
    <form method="post" action="/info">
      <input name="title" placeholder="Titel" required />
      <textarea name="body" placeholder="Text" required></textarea>
      <button type="submit">Info speichern</button>
    </form>
    <div class="list">
      {% for i in infos %}
      <article>
        <h3>{{ i["title"] }}</h3>
        <p>{{ i["body"] }}</p>
        <small>{{ i["updated_at"] }}</small>
        <form method="post" action="/info/delete">
          <input type="hidden" name="info_id" value="{{ i['id'] }}" />
          <button class="danger">Löschen</button>
        </form>
      </article>
      {% endfor %}
    </div>
  </section>

  <section>
    <h2>3. Lager</h2>
    <form method="post" action="/lager">
      <input name="item" placeholder="Gegenstand" required />
      <input name="category" placeholder="Kategorie" value="Sonstiges" />
      <input name="qty" type="number" placeholder="Menge" value="0" />
      <button type="submit">Lager speichern</button>
    </form>
    <div class="list">
      {% for l in lager %}
      <p>{{ l["category"] }} • <strong>{{ l["item"] }}</strong> — {{ l["qty"] }}</p>
      {% endfor %}
    </div>
  </section>

  <section>
    <h2>4. Sanktionskatalog</h2>
    <form method="post" action="/katalog">
      <input name="name" placeholder="Name" required />
      <textarea name="description" placeholder="Beschreibung" required></textarea>
      <button type="submit">Hinzufügen</button>
    </form>
    <div class="list">
      {% for c in catalog %}
      <article>
        <h3>{{ c["name"] }}</h3>
        <p>{{ c["description"] }}</p>
      </article>
      {% endfor %}
    </div>
  </section>

  <section>
    <h2>5. Pflichtausrüstung</h2>
    <form method="post" action="/ausruestung">
      <input name="name" placeholder="z.B. Funk" required />
      <button type="submit">Gegenstand hinzufügen</button>
    </form>
    <div class="list">
      {% for e in eq %}
      <p>{{ e["name"] }}</p>
      {% endfor %}
    </div>
  </section>
</body>
</html>
