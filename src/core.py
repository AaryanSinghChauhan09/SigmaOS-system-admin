"""System admin toolkit for SigmaOS-system-admin (inspired by mintsysadm).

Services, disks, logs and users are handled as pure parsers/filters over
injected command output (systemctl, df, journal, getent) -- nothing here
runs against the real system. The only plan verb (uptime-plan) is pure too:
it decides *when* a reboot should happen, not how to force one.
"""
import argparse, json, re, sys

ENGINE = {
    "name": "sigma-sysadmin",
    "summary": "Inspect services, disks, logs and users from injected facts",
    "language": "python",
    "verbs": ["services", "disks", "logs", "users", "uptime-plan"],
    "principles": ["Pure Parsing", "Fail-Fast", "Least Astonishment",
                   "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-sysadmin services --input systemctl.txt --state failed
$ sigma-sysadmin disks --input df.txt --threshold 90
$ sigma-sysadmin logs --input journal.txt --priority err --since 09:00
$ sigma-sysadmin users --input passwd.txt --shadow shadow.txt
$ sigma-sysadmin uptime-plan --reboot-required --pending-upgrades 12
"""


class SysadminError(Exception):
    pass


# --- services ---

def parse_services(text):
    """Parse `systemctl list-units --type=service --all` style output."""
    services = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("UNIT") or line.startswith("●"):
            line = line.lstrip("●").strip()
            if not line or line.startswith("UNIT"):
                continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) > 4 else ""
        if not unit.endswith(".service"):
            continue
        services.append({"unit": unit, "load": load, "active": active,
                         "sub": sub, "description": desc.strip()})
    return services


def filter_services(services, state=None):
    """Pure: filter by active/load state ('failed', 'inactive', 'active', ...)."""
    if state is None:
        return list(services)
    wanted = {"failed": lambda s: s["active"] == "failed",
              "active": lambda s: s["active"] == "active",
              "inactive": lambda s: s["active"] == "inactive",
              "loaded": lambda s: s["load"] == "loaded",
              "not-found": lambda s: s["load"] == "not-found"}
    if state not in wanted:
        raise SysadminError(f"unknown state {state!r}; choose from {sorted(wanted)}")
    return [s for s in services if wanted[state](s)]


# --- disks ---

def parse_df(text):
    """Parse `df -hP` output -> mount dicts with parsed percentages."""
    disks = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("/dev/"):
            continue
        parts = line.split()
        if len(parts) < 6:
            raise SysadminError(f"bad df line: {line!r}")
        size, used, avail, pct, mount = parts[1:6]
        if not pct.endswith("%"):
            raise SysadminError(f"bad use% in df line: {line!r}")
        disks.append({"device": parts[0], "size": size, "used": used,
                      "avail": avail, "use_pct": int(pct[:-1]),
                      "mount": mount})
    return disks


def low_space(disks, threshold=90):
    """Pure: mounts at/over threshold, sorted worst-first."""
    if not (0 < threshold <= 100):
        raise SysadminError(f"threshold must be 1-100, got {threshold}")
    over = [d for d in disks if d["use_pct"] >= threshold]
    return sorted(over, key=lambda d: -d["use_pct"])


# --- logs ---

_PRIORITY_ORDER = {"emerg": 0, "alert": 1, "crit": 2, "err": 3, "warning": 4,
                   "notice": 5, "info": 6, "debug": 7}


def parse_journal(text):
    """Parse ISO-timestamped journal lines: '2026-10-24T09:15:02+00:00 [err] msg'."""
    entries = []
    pat = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2})?)\s+"
        r"\[(\w+)\]\s+(.*)$")
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        m = pat.match(line)
        if not m:
            raise SysadminError(f"line {lineno}: unparseable journal line {line!r}")
        priority = m.group(2).lower()
        if priority not in _PRIORITY_ORDER:
            raise SysadminError(f"line {lineno}: unknown priority {priority!r}")
        entries.append({"time": m.group(1), "priority": priority,
                        "message": m.group(3)})
    return entries


def filter_logs(entries, priority="err", since=None, contains=None):
    """Pure: entries at or below priority, at/after `since`, optional substring."""
    if priority not in _PRIORITY_ORDER:
        raise SysadminError(f"unknown priority {priority!r}")
    cutoff = _PRIORITY_ORDER[priority]
    out = []
    for e in entries:
        if _PRIORITY_ORDER[e["priority"]] > cutoff:
            continue
        if since and e["time"] < since:  # ISO timestamps sort lexicographically
            continue
        if contains and contains.lower() not in e["message"].lower():
            continue
        out.append(e)
    return out


# --- users ---

def parse_passwd(text):
    """Parse passwd-style lines: name:pw:uid:gid:gecos:home:shell."""
    users = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) != 7:
            raise SysadminError(f"line {lineno}: bad passwd line {line!r}")
        name, pw, uid, gid, gecos, home, shell = parts
        users.append({"name": name, "password": pw, "uid": int(uid),
                      "gid": int(gid), "gecos": gecos, "home": home,
                      "shell": shell})
    return users


def audit_users(users, shadows=()):
    """Pure: flag risky accounts (no password, uid 0 extras, shells for service)."""
    shadow_pw = {s["name"]: s["password"] for s in shadows}
    findings = []
    for u in users:
        pw = shadow_pw.get(u["name"], u["password"])
        if pw in ("", "!") and u["uid"] >= 1000:
            findings.append({"user": u["name"], "issue": "no-password",
                             "severity": "high"})
        elif pw == "*" and u["uid"] >= 1000:
            findings.append({"user": u["name"], "issue": "locked",
                             "severity": "info"})
        if u["uid"] == 0 and u["name"] != "root":
            findings.append({"user": u["name"], "issue": "extra-uid0",
                             "severity": "high"})
        if u["uid"] >= 1000 and u["shell"] in ("/usr/sbin/nologin", "/bin/false"):
            findings.append({"user": u["name"], "issue": "nologin-user-shell-ok",
                             "severity": "info"})
    return findings


def parse_shadow(text):
    """Parse shadow-style lines: name:password:days... (only first two fields)."""
    shadows = []
    for raw in text.splitlines():
        parts = raw.strip().split(":")
        if len(parts) >= 2 and parts[0]:
            shadows.append({"name": parts[0], "password": parts[1]})
    return shadows


# --- uptime plan ---

def plan_uptime(facts):
    """Pure: should we reboot? facts: uptime_hours, reboot_required,
    pending_upgrades, service_failures."""
    reasons = []
    if facts.get("reboot_required"):
        reasons.append("userspace/kernel mismatch: /var/run/reboot-required present")
    if facts.get("pending_upgrades", 0) > 0:
        reasons.append(f"{facts['pending_upgrades']} pending upgrade(s) may include a kernel")
    if facts.get("service_failures", 0) >= 3:
        reasons.append(f"{facts['service_failures']} failed services; a reboot clears transient states")
    if facts.get("uptime_hours", 0) >= 24 * 30:
        reasons.append(f"uptime {facts['uptime_hours']}h exceeds 30 days")
    if not reasons:
        return {"reboot": False, "window": None, "reasons": []}
    # pick the least-disruptive window: next 02:00-05:00 local slot
    window = "02:00-05:00"
    return {"reboot": True, "window": window, "reasons": reasons,
            "commands": ["shutdown -r +10 'SigmaOS: rebooting for updates'"]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("services", help="parse + filter service states")
    sv.add_argument("--input", required=True, help="systemctl-like output file")
    sv.add_argument("--state", default=None)
    dk = sub.add_parser("disks", help="parse df output; flag low space")
    dk.add_argument("--input", required=True)
    dk.add_argument("--threshold", type=int, default=90)
    lg = sub.add_parser("logs", help="filter journal-like lines")
    lg.add_argument("--input", required=True)
    lg.add_argument("--priority", default="err")
    lg.add_argument("--since", default=None, help="ISO time lower bound")
    lg.add_argument("--contains", default=None)
    us = sub.add_parser("users", help="audit user accounts")
    us.add_argument("--input", required=True, help="passwd-like file")
    us.add_argument("--shadow", default=None, help="shadow-like file")
    up = sub.add_parser("uptime-plan", help="decide whether/when to reboot")
    up.add_argument("--uptime-hours", type=float, default=0)
    up.add_argument("--reboot-required", action="store_true")
    up.add_argument("--pending-upgrades", type=int, default=0)
    up.add_argument("--service-failures", type=int, default=0)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "services":
            with open(args.input) as fh:
                services = parse_services(fh.read())
            for s in filter_services(services, args.state):
                print(f"{s['unit']:40} {s['active']:10} {s['sub']}")
        elif args.cmd == "disks":
            with open(args.input) as fh:
                disks = parse_df(fh.read())
            low = low_space(disks, args.threshold)
            if not low:
                print(f"all mounts below {args.threshold}%")
            for d in low:
                print(f"{d['mount']:20} {d['use_pct']}% full "
                      f"({d['avail']} free on {d['device']})")
            return 1 if low else 0
        elif args.cmd == "logs":
            with open(args.input) as fh:
                entries = parse_journal(fh.read())
            for e in filter_logs(entries, args.priority, args.since, args.contains):
                print(f"{e['time']} [{e['priority']}] {e['message']}")
        elif args.cmd == "users":
            with open(args.input) as fh:
                users = parse_passwd(fh.read())
            shadows = []
            if args.shadow:
                with open(args.shadow) as fh:
                    shadows = parse_shadow(fh.read())
            for f in audit_users(users, shadows):
                print(f"{f['severity'].upper():6} {f['user']}: {f['issue']}")
        elif args.cmd == "uptime-plan":
            plan = plan_uptime({"uptime_hours": args.uptime_hours,
                                "reboot_required": args.reboot_required,
                                "pending_upgrades": args.pending_upgrades,
                                "service_failures": args.service_failures})
            print(json.dumps(plan, indent=2))
        return 0
    except (SysadminError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    systemctl = """\
  UNIT                      LOAD   ACTIVE SUB     DESCRIPTION
  accounts-daemon.service   loaded active running Accounts Service
  bluetooth.service         loaded active running Bluetooth service
● cupsd.service             loaded failed failed  CUPS Scheduler
  ssh.service               loaded inactive dead   OpenSSH server
  ghost.service             not-found not-found ghost
"""

    services = parse_services(systemctl)
    names = [s["unit"] for s in services]
    assert names == ["accounts-daemon.service", "bluetooth.service",
                     "cupsd.service", "ssh.service", "ghost.service"], names
    cupsd = [s for s in services if s["unit"] == "cupsd.service"][0]
    assert cupsd["active"] == "failed" and cupsd["sub"] == "failed"
    assert [s["unit"] for s in filter_services(services, "failed")] == ["cupsd.service"]
    assert [s["unit"] for s in filter_services(services, "not-found")] == ["ghost.service"]
    assert len(filter_services(services)) == 5
    try:
        filter_services(services, "exploded")
    except SysadminError:
        pass
    else:
        raise AssertionError("bad state not caught")

    df = """\
Filesystem     Size  Used Avail Use% Mounted on
/dev/nvme0n1p2 468G  391G   54G  88% /
/dev/nvme0n1p1 511M  6.1M  505M   2% /boot/efi
/dev/sda1      1.8T  1.8T   40G  98% /home
tmpfs          7.8G  2.1M  7.8G   1% /run
"""
    disks = parse_df(df)
    assert [d["mount"] for d in disks] == ["/", "/boot/efi", "/home"]
    assert disks[2]["use_pct"] == 98
    low = low_space(disks, 90)
    assert [d["mount"] for d in low] == ["/home"]
    assert low_space(disks, 99) == []
    try:
        low_space(disks, 0)
    except SysadminError:
        pass
    else:
        raise AssertionError("bad threshold not caught")
    try:
        parse_df("/dev/sda1 10G\n")
    except SysadminError:
        pass
    else:
        raise AssertionError("bad df line not caught")

    journal = """\
2026-10-24T09:15:02+00:00 [info] starting sigma-session
2026-10-24T09:16:10+00:00 [err] failed to reach mirror.example
2026-10-24T09:17:00+00:00 [warning] retrying in 30s
2026-10-24T10:01:45+00:00 [err] mirror still unreachable
2026-10-24T10:02:00+00:00 [info] fallback mirror selected
"""
    entries = parse_journal(journal)
    assert [e["priority"] for e in entries] == ["info", "err", "warning", "err", "info"]
    errs = filter_logs(entries, "err")
    assert len(errs) == 2
    late = filter_logs(entries, "err", since="2026-10-24T10:00:00")
    assert len(late) == 1 and "still unreachable" in late[0]["message"]
    assert len(filter_logs(entries, "debug")) == 5  # debug includes everything
    assert len(filter_logs(entries, "err", contains="MIRROR")) == 2
    try:
        parse_journal("garbage line\n")
    except SysadminError as e:
        assert "unparseable" in str(e)
    else:
        raise AssertionError("bad journal line not caught")
    try:
        filter_logs(entries, "loud")
    except SysadminError:
        pass
    else:
        raise AssertionError("bad priority not caught")

    passwd = """\
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
alice:x:1000:1000:Alice:/home/alice:/bin/bash
bob:x:1001:1001:Bob:/home/bob:/bin/bash
svc:x:1002:1002:Service acct:/var/lib/svc:/usr/sbin/nologin
mallory:x:0:0:Extra Root:/home/mallory:/bin/bash
"""
    shadow = """\
root:$6$abc$hash:19000:0:99999:7:::
alice:$6$def$hash:19000:0:99999:7:::
bob::19000:0:99999:7:::
svc:*:19000:0:99999:7:::
mallory:$6$ghi$hash:19000:0:99999:7:::
"""
    users = parse_passwd(passwd)
    assert [u["name"] for u in users] == ["root", "daemon", "alice", "bob",
                                          "svc", "mallory"]
    findings = audit_users(users, parse_shadow(shadow))
    by_user = {}
    for f in findings:
        by_user.setdefault(f["user"], []).append(f["issue"])
    assert "no-password" in by_user["bob"]           # empty shadow password
    assert "extra-uid0" in by_user["mallory"]
    assert "locked" in by_user["svc"]
    assert "alice" not in by_user and "root" not in by_user
    try:
        parse_passwd("badline\n")
    except SysadminError:
        pass
    else:
        raise AssertionError("bad passwd line not caught")

    # uptime planning
    quiet = plan_uptime({"uptime_hours": 5})
    assert quiet["reboot"] is False and quiet["reasons"] == []
    plan = plan_uptime({"uptime_hours": 24 * 31, "reboot_required": True,
                        "pending_upgrades": 12, "service_failures": 3})
    assert plan["reboot"] is True and plan["window"] == "02:00-05:00"
    assert len(plan["reasons"]) == 4
    assert plan["commands"][0].startswith("shutdown -r")
    long_up = plan_uptime({"uptime_hours": 24 * 45})
    assert long_up["reboot"] is True
    assert any("30 days" in r for r in long_up["reasons"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
