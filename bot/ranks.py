# Eure Discord-Rollen, von oben nach unten. Namen müssen EXAKT stimmen.
RANK_ROLE_NAMES = [
    "Rang 12 – OG",
    "Rang 11 – Consigliere",
    "Rang 10 – Don",
    "Rang 9 – Capo",
    "Rang 8 – Lieutenant",
    "Rang 7 – Enforcer",
    "Rang 6 – Made Member",
    "Rang 5 – Soldier",
    "Rang 4 – Prospect",
    "Rang 3 – Recruit",
    "Rang 2 – Runner",
    "Rang 1 – Associate",
]

LEADER_ROLES = {
    "Führung",
    "Rang 12 – OG",
    "Rang 11 – Consigliere",
    "Rang 10 – Don",
    "Rang 9 – Capo",
}

OFFICER_ROLES = LEADER_ROLES | {
    "Rang 9 – Capo",
    "Rang 8 – Lieutenant",
}

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


def is_leader(member):
    names = member_role_names(member)
    return bool(names & cfg(member.guild)["leaders"]) or member.guild_permissions.administrator


def is_officer(member):
    names = member_role_names(member)
    return bool(names & cfg(member.guild)["officers"]) or member.guild_permissions.administrator


def is_staff(member):
    names = member_role_names(member)
    ranks = set(rank_names(member.guild))
    return bool(names & ranks) or member.guild_permissions.administrator


def highest_rank(member):
    names = member_role_names(member)
    for rank in rank_names(member.guild):
        if rank in names:
            return rank
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
    return f"{status_dot(member)} {member.mention} | {nick}"
