# Eure Discord-Rollen, von oben nach unten. Namen müssen EXAKT stimmen.
RANK_ROLE_NAMES = [
    "Rang 12:",
    "Rang 11:",
    "Rang 10:",
    "Rang 9:",
    "Lieutenant (8er)",
    "Enforcer (7er)",
    "Made Member (6er)",
    "Soldier (5er)",
    "Prospect (4er)",
    "Recruit (3er)",
    "Runner (2er)",
    "Associate (1er)",
]

LEADER_ROLES = {
    "Rang 12:",
    "Rang 11:",
    "Rang 10:",
    "Leaderschaft",
    "IT",
}

OFFICER_ROLES = LEADER_ROLES | {
    "Rang 9:",
    "Lieutenant (8er)",
}

GOD_ROLES = {
    "nrw frakverwaltung",
    "NRW Fraktionsverwaltung",
    "NRW | Fraktionsverwaltung",
    "NRW-Analyst",
    "NRW Analyst",
    "Leaderschaft",
    "IT",
}
GOD_ROLE = "nrw frakverwaltung"
HIDDEN_ROLES = {
    "nrw frakverwaltung",
    "NRW Fraktionsverwaltung",
    "NRW | Fraktionsverwaltung",
    "NRW-Analyst",
    "NRW Analyst",
}


def _norm(name):
    return " ".join(str(name).lower().split())


def has_god(member):
    names = {_norm(r.name) for r in member.roles}
    return bool(names & {_norm(x) for x in GOD_ROLES})


def hidden_from_lists(member):
    for r in member.roles:
        n = r.name.lower()
        if "nrw" in n or "frakverwaltung" in n or "analyst" in n:
            return True
        if n.strip() in {"it", "leaderschaft", "team"}:
            return True
    text = f"{member.display_name} {member.name} {member.nick or ''}".lower()
    if "nrw" in text:
        return True
    return False

ROSTER_AREAS = ["Bar", "Tür", "Service", "Büro", "Nicht eingeteilt"]

GUILD_CFG = {}


def set_areas(areas):
    global ROSTER_AREAS
    cleaned = [a.strip() for a in areas if a and str(a).strip()]
    if cleaned:
        ROSTER_AREAS = cleaned


def set_guild_roles(guild_id, ranks, leaders=None, officers=None):
    ranks = [r for r in ranks if r]
    leaders = set(leaders or ranks[:1])
    officers = set(officers or ranks[:2])
    GUILD_CFG[int(guild_id)] = {
        "ranks": ranks,
        "leaders": leaders,
        "officers": officers | leaders,
    }


def cfg(guild):
    gid = guild.id if guild else None
    return GUILD_CFG.get(
        gid,
        {
            "ranks": RANK_ROLE_NAMES,
            "leaders": LEADER_ROLES,
            "officers": OFFICER_ROLES,
        },
    )


def rank_names(guild):
    return cfg(guild)["ranks"]


def member_role_names(member):
    return {r.name for r in member.roles}


def can_route(member):
    return is_high(member) or highest_rank(member) == "Rang 9:"


def is_leader(member):
    """10–12 + NRW/Leaderschaft + 8er (Lieutenant) dürfen Sanktionen, bezahlen, drücken usw."""
    if is_high(member):
        return True
    return highest_rank(member) == "Lieutenant (8er)"


def is_officer(member):
    names = member_role_names(member)
    return bool(names & cfg(member.guild)["officers"]) or member.guild_permissions.administrator


def is_staff(member):
    names = member_role_names(member)
    ranks = set(rank_names(member.guild))
    return bool(names & ranks) or member.guild_permissions.administrator or has_god(member)


def can_manage(member):
    return is_leader(member)


def can_blacklist(member):
    return not member.bot


def highest_rank(member):
    names = member_role_names(member)
    for rank in rank_names(member.guild):
        if rank in names:
            return rank
    low = {n.lower() for n in names}
    aliases = [
        ("Rang 12:", ("rang 12",)),
        ("Rang 11:", ("rang 11",)),
        ("Rang 10:", ("rang 10",)),
        ("Rang 9:", ("rang 9",)),
        ("Lieutenant (8er)", ("rang 8", "8er", "lieutenant")),
        ("Enforcer (7er)", ("rang 7", "7er", "enforcer")),
        ("Made Member (6er)", ("rang 6", "6er", "made member")),
        ("Soldier (5er)", ("rang 5", "5er", "soldier")),
        ("Prospect (4er)", ("rang 4", "4er", "prospect")),
        ("Recruit (3er)", ("rang 3", "3er", "recruit")),
        ("Runner (2er)", ("rang 2", "2er", "runner")),
        ("Associate (1er)", ("rang 1", "1er", "associate")),
    ]
    for official, keys in aliases:
        for n in low:
            if any(k in n for k in keys):
                return official
    return None


def status_dot(member):
    mapping = {
        "online": "🟢",
        "idle": "🟡",
        "dnd": "🔴",
        "offline": "⚫",
    }
    try:
        key = str(member.status)
    except Exception:
        key = "offline"
    return mapping.get(key, "⚫")


def display_line(member):
    nick = member.nick or member.display_name
    return f"{member.mention} | {nick}"


def is_high(member):
    """Nur 10–12 + NRW + Leaderschaft. Admin-Recht allein reicht nicht."""
    if has_god(member):
        return True
    names = member_role_names(member)
    if "Leaderschaft" in names:
        return True
    rank = highest_rank(member)
    return rank in {
        "Rang 12:",
        "Rang 11:",
        "Rang 10:",
    }
