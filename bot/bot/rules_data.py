SANCTION_RULES = [
    (1, "Zu spät zur Aufstellung ankommen", "15k"),
    (2, "Nicht abmelden", "50k"),
    (3, "Nicht für den Tag abgemeldet sein", "25k"),
    (4, "GPS muss eingeschaltet sein, wenn ihr wach seid", "30k"),
    (5, "Funk muss eingeschaltet sein, wenn ihr wach seid", "30k"),
    (6, "Im Funk stören oder unnötig reden", "15k"),
    (7, "Fehlende Funkdisziplin", "20k"),
    (8, "Befehle während einer Aktion ignorieren", "50k"),
    (9, "Bei einer Familienaktion AFK gehen", "30k"),
    (10, "Missachtung einer Anweisung", "20k"),
    (11, "Respektloses Verhalten gegenüber der Führung", "50k"),
    (12, "Falsches Verhalten gegenüber anderen Familien", "100k"),
    (13, "Unnötiger Stress mit anderen Familien", "100k"),
    (14, "Verrat", "BLOODOUT"),
    (15, "Interne Informationen weitergeben", "BLOODOUT"),
    (16, "Internen Streit öffentlich austragen", "100k"),
    (17, "Streit innerhalb der Familie provozieren", "50k"),
    (18, "Familienmitglieder beleidigen", "40k"),
    (19, "Keine Familienkleidung tragen", "100k"),
    (20, "Ausrüstung nach einer Aktion nicht zurückgeben", "25k"),
    (21, "Diebstahl innerhalb der Familie", "500k"),
    (22, "Bei einer Kolonnenfahrt unnötig überholen oder absichtlich rammen", "50k"),
    (23, "Fraktionsfahrzeuge müssen immer abgeschlossen werden", "25k"),
    (24, "Fraktionsfahrzeuge einfach stehen lassen", "20k"),
    (25, "Wochenabgabe nicht rechtzeitig abgeben", "100k"),
    (26, "Nach wiederholter Aufforderung die Wochenabgabe nicht abgeben", "DOPPELTER WERT"),
    (27, "Wiederholtes Fehlverhalten trotz Verwarnung", "BLOODOUT"),
]

RANK_INFO = [
    ("Rang 12 – OG", "Oberster Anführer der Familie."),
    ("Rang 11 – Consigliere", "Rechte Hand des Dons und Stellvertreter."),
    ("Rang 10 – Don", "Berater des Dons und Vermittler bei internen Angelegenheiten."),
    ("Rang 9 – Capo", "Leitet eine Crew und trägt Verantwortung für seine Mitglieder (Routenverwaltung)."),
    ("Rang 8 – Lieutenant", "Unterstützt den Capo und übernimmt organisatorische Aufgaben."),
    ("Rang 7 – Enforcer", "Erfahrenes Mitglied, sorgt für Ordnung und Disziplin innerhalb der Familie (Caller)."),
    ("Rang 6 – Made Member", "Vollwertiges und anerkanntes Mitglied."),
    ("Rang 5 – Soldier", "Aktives Mitglied, das sich bereits bewiesen hat."),
    ("Rang 4 – Prospect", "Anwärter der Liederschaft."),
    ("Rang 3 – Recruit", "Muss sich noch beweisen."),
    ("Rang 2 – Runner", "Hilft der Familie und sammelt erste Erfahrungen."),
    ("Rang 1 – Associate", "Anfänger (auf Probe)."),
]

EQUIPMENT_TEXT = """**Freizeit**
1. Bandagen
2. Reparatur Kasten
3. GPS
4. Handy (Funk)
5. Klammerpflaster

**In Fights oder Kämpfen**
1. Waffe
2. Ersatz Magazine
3. Bandagen
4. Klammerpflaster
5. Reparatur Kasten
6. Handy (Funk)
7. GPS
8. Handschellen
9. Westen (Schutz)

**Pflicht Fahrzeuge**
• BF 400
• BF 900
• nrwvorsch
• nrwballer"""

CLIP_RULES = (
    "Nur LMS (GW) Modus.\n"
    "Offene Straße, Lootdrop und Labor.\n"
    "Kill-Clips müssen 5 Sekunden vor und nach der Aktion gehen, insgesamt 15 Sekunden."
)
