# Reihenfolge von oben nach unten wie auf der Mitarbeiterliste
RANK_ROLE_NAMES = [
    "Geschäftsleitung",
    "Clubleitung",
    "Leitende Servicekraft",
    "Servicekraft",
    "Junior-Servicekraft",
    "Auszubildende/r",
]

LEADER_ROLES = {"Geschäftsleitung", "Clubleitung"}
OFFICER_ROLES = LEADER_ROLES | {"Leitende Servicekraft"}

ROSTER_AREAS = ["Bar", "Tür", "Service", "Büro", "Nicht eingeteilt"]


def member_role_names(member):
    return {r.name for r in member.roles}


def is_leader(member):
    names = member_role_names(member)
    return bool(names & LEADER_ROLES) or member.guild_permissions.administrator


def is_officer(member):
    names = member_role_names(member)
    return bool(names & OFFICER_ROLES) or member.guild_permissions.administrator


def is_staff(member):
    names = member_role_names(member)
    return bool(names & set(RANK_ROLE_NAMES)) or member.guild_permissions.administrator


def highest_rank(member):
    names = member_role_names(member)
    for rank in RANK_ROLE_NAMES:
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
