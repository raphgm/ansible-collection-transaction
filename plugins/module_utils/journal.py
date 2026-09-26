# Copyright: (c) 2026, Raphael Gab-Momoh
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

"""On-host transaction journal.

The journal lives on the managed host, so a rollback can still be run after the
controller dies or loses its connection. Layout::

    <journal_dir>/<txn_id>/journal.json
    <journal_dir>/<txn_id>/files/<n>      # saved copies of original files

Only the first snapshot of a given resource counts: it is the state from
before the transaction touched it, which is what a rollback must restore.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time

DEFAULT_JOURNAL_DIR = "/var/lib/ansible-transaction"
JOURNAL_VERSION = 1

OPEN = "open"
COMMITTED = "committed"
ROLLED_BACK = "rolled_back"
ROLLBACK_FAILED = "rollback_failed"


class JournalError(Exception):
    pass


def _run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


class Journal:
    def __init__(self, journal_dir, txn_id, runner=_run):
        if not txn_id or "/" in txn_id or txn_id in (".", ".."):
            raise JournalError("invalid transaction id: %r" % txn_id)
        self.root = os.path.join(journal_dir, txn_id)
        self.path = os.path.join(self.root, "journal.json")
        self.files_dir = os.path.join(self.root, "files")
        self.txn_id = txn_id
        self._runner = runner
        self.data = None

    def run(self, cmd):
        """Run a command; output is stripped (AnsibleModule.run_command keeps the trailing newline)."""
        rc, out, err = self._runner(cmd)
        return rc, out.strip(), err.strip()

    # ------------------------------------------------------------ lifecycle

    def exists(self):
        return os.path.exists(self.path)

    def load(self):
        if not self.exists():
            raise JournalError("no transaction '%s' at %s; run begin first" % (self.txn_id, self.root))
        with open(self.path) as f:
            self.data = json.load(f)
        return self.data

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, self.path)

    def begin(self, force=False):
        """Open a transaction. Returns True if a new one was created."""
        if self.exists():
            status = self.load()["status"]
            if status == OPEN and not force:
                raise JournalError(
                    "transaction '%s' is still open from an earlier run (%s). It was never committed "
                    "or rolled back: run rollback to restore it, or begin with force=true to discard it."
                    % (self.txn_id, self.root))
            shutil.rmtree(self.root)
        os.makedirs(self.files_dir, mode=0o700)
        os.chmod(self.root, 0o700)
        self.data = {"version": JOURNAL_VERSION, "id": self.txn_id, "status": OPEN,
                     "started": time.time(), "entries": []}
        self.save()
        return True

    def commit(self, keep=False):
        self.load()
        if self.data["status"] != OPEN:
            raise JournalError("transaction '%s' is %s, not open" % (self.txn_id, self.data["status"]))
        if keep:
            self.data["status"] = COMMITTED
            self.save()
            shutil.rmtree(self.files_dir, ignore_errors=True)
        else:
            shutil.rmtree(self.root)

    # ------------------------------------------------------------ snapshot

    def _has(self, kind, name):
        return any(e["kind"] == kind and e["name"] == name for e in self.data["entries"])

    def _require_open(self):
        if self.data["status"] != OPEN:
            raise JournalError("transaction '%s' is %s, not open" % (self.txn_id, self.data["status"]))

    def snapshot(self, paths=(), packages=(), services=(), package_manager="auto"):
        """Record current state. Returns list of newly recorded entries."""
        self.load()
        self._require_open()
        added = []
        for p in paths:
            p = os.path.abspath(p)
            if not self._has("file", p):
                added.append(self._snapshot_file(p))
        if packages:
            mgr = detect_package_manager(self.run) if package_manager == "auto" else package_manager
            for name in packages:
                if not self._has("package", name):
                    added.append({"kind": "package", "name": name, "manager": mgr,
                                  "version": package_version(self.run, mgr, name)})
        for name in services:
            if not self._has("service", name):
                added.append(self._snapshot_service(name))
        self.data["entries"].extend(added)
        self.save()
        return added

    def _snapshot_file(self, path):
        entry = {"kind": "file", "name": path, "existed": os.path.lexists(path)}
        if not entry["existed"]:
            return entry
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            raise JournalError("%s is a directory; only files and symlinks can be snapshotted" % path)
        entry.update(mode=stat.S_IMODE(st.st_mode), uid=st.st_uid, gid=st.st_gid)
        if stat.S_ISLNK(st.st_mode):
            entry["link"] = os.readlink(path)
        else:
            backup = str(len(os.listdir(self.files_dir)))
            shutil.copy2(path, os.path.join(self.files_dir, backup))
            entry["backup"] = backup
        return entry

    def _snapshot_service(self, name):
        rc, out, dummy = self.run(["systemctl", "is-active", name])
        active = out == "active"
        rc, out, dummy = self.run(["systemctl", "is-enabled", name])
        enabled = {"enabled": True, "disabled": False}.get(out)  # static/masked/etc: leave alone
        return {"kind": "service", "name": name, "active": active, "enabled": enabled}

    # ------------------------------------------------------------ rollback

    def rollback(self, restart_services=True):
        """Restore snapshot state. Returns (restored, errors).

        Files and packages are restored newest-first, then services, so a
        service is (re)started only after its config and binaries are back.
        """
        self.load()
        if self.data["status"] == COMMITTED:
            raise JournalError("transaction '%s' is committed; nothing to roll back" % self.txn_id)
        entries = list(reversed(self.data["entries"]))
        ordered = [e for e in entries if e["kind"] != "service"] + [e for e in entries if e["kind"] == "service"]
        restored, errors = [], []
        for e in ordered:
            try:
                if getattr(self, "_restore_" + e["kind"])(e, restart_services):
                    restored.append("%s:%s" % (e["kind"], e["name"]))
            except Exception as exc:  # keep going: restore as much as possible
                errors.append("%s:%s: %s" % (e["kind"], e["name"], exc))
        self.data["status"] = ROLLBACK_FAILED if errors else ROLLED_BACK
        self.save()
        return restored, errors

    def _restore_file(self, e, restart):  # pylint: disable=unused-argument
        path = e["name"]
        if not e["existed"]:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
                return True
            if os.path.lexists(path):
                os.unlink(path)
                return True
            return False
        if "link" in e:
            if os.path.islink(path) and os.readlink(path) == e["link"]:
                return False
            if os.path.lexists(path):
                os.unlink(path)
            os.symlink(e["link"], path)
            return True
        src = os.path.join(self.files_dir, e["backup"])
        if _same_file(src, path, e):
            return False
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        tmp = path + ".ansible-txn-restore"
        shutil.copy2(src, tmp)
        os.chown(tmp, e["uid"], e["gid"])
        os.chmod(tmp, e["mode"])
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        os.rename(tmp, path)
        return True

    def _restore_package(self, e, restart):  # pylint: disable=unused-argument
        current = package_version(self.run, e["manager"], e["name"])
        if current == e["version"]:
            return False
        mgr, name, ver = e["manager"], e["name"], e["version"]
        if ver is None:
            cmds = [{"apt": ["apt-get", "-y", "remove", name]}.get(mgr, [mgr, "-y", "remove", name])]
        elif mgr == "apt":
            cmds = [["apt-get", "-y", "--allow-downgrades", "install", "%s=%s" % (name, ver)]]
        else:
            spec = "%s-%s" % (name, ver)
            cmds = [[mgr, "-y", "downgrade", spec], [mgr, "-y", "install", spec]]
        for cmd in cmds:
            rc, out, err = self.run(cmd)
            if rc == 0 and package_version(self.run, mgr, name) == ver:
                return True
        raise JournalError("could not restore %s to %s: %s" % (name, ver or "absent", err or out))

    def _restore_service(self, e, restart):
        name, changed = e["name"], False
        if e["enabled"] is not None:
            rc, out, dummy = self.run(["systemctl", "is-enabled", name])
            if (out == "enabled") != e["enabled"]:
                self._must(["systemctl", "enable" if e["enabled"] else "disable", name])
                changed = True
        if e["active"]:
            # restart so the service picks up the restored config/binaries
            self._must(["systemctl", "restart" if restart else "start", name])
            changed = True
        else:
            rc, out, dummy = self.run(["systemctl", "is-active", name])
            if out == "active":
                self._must(["systemctl", "stop", name])
                changed = True
        return changed

    def _must(self, cmd):
        rc, out, err = self.run(cmd)
        if rc != 0:
            raise JournalError("%s failed: %s" % (" ".join(cmd), err or out))


def _same_file(a, b, e):
    if not os.path.isfile(b) or os.path.islink(b):
        return False
    st = os.stat(b)
    if (stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid) != (e["mode"], e["uid"], e["gid"]):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def detect_package_manager(run):
    for mgr in ("apt", "dnf", "yum"):
        rc, dummy, dummy = run(["sh", "-c", "command -v %s" % ("dpkg-query" if mgr == "apt" else mgr)])
        if rc == 0:
            return mgr
    raise JournalError("no supported package manager found (apt, dnf, yum)")


def package_version(run, mgr, name):
    """Installed version, or None if not installed."""
    if mgr == "apt":
        rc, out, dummy = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", name])
        if rc != 0 or not out.startswith("ii"):
            return None
        return out.split("|", 1)[1]
    rc, out, dummy = run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", name])
    return out if rc == 0 else None
