# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import annotations

import os

import pytest

from ansible_collections.raphgm.transaction.plugins.module_utils.journal import (
    COMMITTED, ROLLED_BACK, ROLLBACK_FAILED, Journal, JournalError)


class FakeHost:
    """Pretend package manager + systemd, driven through the runner hook."""

    def __init__(self):
        self.pkgs = {"nginx": "1.24.0-1"}
        self.active = {"nginx": True}
        self.enabled = {"nginx": True}
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "dpkg-query":
            v = self.pkgs.get(cmd[-1])
            return (0, "ii |" + v, "") if v else (1, "", "not installed")
        if cmd[:2] == ["apt-get", "-y"]:
            if cmd[2] == "remove":
                self.pkgs.pop(cmd[3], None)
            else:
                name, ver = cmd[-1].split("=")
                self.pkgs[name] = ver
            return 0, "", ""
        if cmd[0] == "systemctl":
            action, name = cmd[1], cmd[2]
            if action == "is-active":
                return 0, "active" if self.active.get(name) else "inactive", ""
            if action == "is-enabled":
                return 0, "enabled" if self.enabled.get(name) else "disabled", ""
            if action in ("start", "restart"):
                self.active[name] = True
            elif action == "stop":
                self.active[name] = False
            elif action in ("enable", "disable"):
                self.enabled[name] = action == "enable"
            return 0, "", ""
        raise AssertionError(cmd)


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def journal(tmp_path, host):
    j = Journal(str(tmp_path / "journal"), "t1", runner=host)
    j.begin()
    return j


def write(path, text, mode=0o644):
    path.write_text(text)
    os.chmod(path, mode)


def test_restores_changed_file_and_mode(tmp_path, journal):
    f = tmp_path / "app.conf"
    write(f, "v1", 0o640)
    journal.snapshot(paths=[str(f)])
    write(f, "v2", 0o777)
    restored, errors = journal.rollback()
    assert errors == []
    assert f.read_text() == "v1"
    assert oct(os.stat(f).st_mode & 0o777) == oct(0o640)
    assert restored == ["file:%s" % f]
    assert journal.data["status"] == ROLLED_BACK


def test_removes_file_that_did_not_exist(tmp_path, journal):
    f = tmp_path / "new.conf"
    journal.snapshot(paths=[str(f)])
    f.write_text("created")
    journal.rollback()
    assert not f.exists()


def test_removes_directory_created_at_new_path(tmp_path, journal):
    d = tmp_path / "newdir"
    journal.snapshot(paths=[str(d)])
    d.mkdir()
    (d / "x").write_text("x")
    journal.rollback()
    assert not d.exists()


def test_restores_symlink_target(tmp_path, journal):
    link = tmp_path / "current"
    os.symlink("release-1", link)
    journal.snapshot(paths=[str(link)])
    os.unlink(link)
    os.symlink("release-2", link)
    journal.rollback()
    assert os.readlink(link) == "release-1"


def test_first_snapshot_wins(tmp_path, journal):
    f = tmp_path / "app.conf"
    write(f, "original")
    journal.snapshot(paths=[str(f)])
    write(f, "middle")
    assert journal.snapshot(paths=[str(f)]) == []
    journal.rollback()
    assert f.read_text() == "original"


def test_rollback_is_idempotent(tmp_path, journal):
    f = tmp_path / "app.conf"
    write(f, "v1")
    journal.snapshot(paths=[str(f)])
    write(f, "v2")
    assert journal.rollback()[0]
    assert journal.rollback() == ([], [])


def test_existing_directory_rejected(tmp_path, journal):
    with pytest.raises(JournalError, match="directory"):
        journal.snapshot(paths=[str(tmp_path)])


def test_package_downgrade_and_removal(journal, host):
    journal.snapshot(packages=["nginx", "redis"], package_manager="apt")
    host.pkgs["nginx"] = "1.26.0-1"
    host.pkgs["redis"] = "7.0"
    restored, errors = journal.rollback()
    assert errors == []
    assert host.pkgs == {"nginx": "1.24.0-1"}
    assert ["apt-get", "-y", "--allow-downgrades", "install", "nginx=1.24.0-1"] in host.calls


def test_services_restored_after_files(tmp_path, journal, host):
    f = tmp_path / "nginx.conf"
    write(f, "good")
    journal.snapshot(services=["nginx"])
    journal.snapshot(paths=[str(f)])
    write(f, "bad")
    host.enabled["nginx"] = False
    host.calls.clear()
    restored, _ = journal.rollback()
    assert restored == ["file:%s" % f, "service:nginx"]
    assert ["systemctl", "restart", "nginx"] in host.calls
    assert host.enabled["nginx"] is True


def test_service_stopped_if_it_was_stopped(journal, host):
    host.active["nginx"] = False
    journal.snapshot(services=["nginx"])
    host.active["nginx"] = True
    journal.rollback()
    assert host.active["nginx"] is False


def test_errors_collected_and_rest_still_restored(tmp_path, journal, host):
    f = tmp_path / "a.conf"
    write(f, "v1")
    journal.snapshot(paths=[str(f)], packages=["nginx"], package_manager="apt")
    write(f, "v2")
    host.pkgs["nginx"] = "9"
    orig = host.__call__

    def broken(cmd):
        if cmd[0] == "apt-get":
            return 100, "", "E: Version '1.24.0-1' for 'nginx' was not found"
        return orig(cmd)
    journal.run = broken
    restored, errors = journal.rollback()
    assert f.read_text() == "v1"
    assert len(errors) == 1 and "not found" in errors[0]
    assert journal.data["status"] == ROLLBACK_FAILED


def test_begin_refuses_leftover_open_transaction(tmp_path, host):
    Journal(str(tmp_path), "t", runner=host).begin()
    with pytest.raises(JournalError, match="still open"):
        Journal(str(tmp_path), "t", runner=host).begin()
    assert Journal(str(tmp_path), "t", runner=host).begin(force=True)


def test_rollback_works_from_fresh_process(tmp_path, host):
    f = tmp_path / "app.conf"
    write(f, "v1")
    j = Journal(str(tmp_path / "j"), "t", runner=host)
    j.begin()
    j.snapshot(paths=[str(f)])
    write(f, "v2")
    # controller "crashed"; a new run picks up the on-host journal
    Journal(str(tmp_path / "j"), "t", runner=host).rollback()
    assert f.read_text() == "v1"


def test_commit_removes_journal(journal):
    journal.commit()
    assert not os.path.exists(journal.root)


def test_commit_keep_journal(journal):
    journal.commit(keep=True)
    assert journal.load()["status"] == COMMITTED
    with pytest.raises(JournalError, match="committed"):
        journal.rollback()


@pytest.mark.parametrize("bad", ["", "../x", "a/b", ".."])
def test_invalid_id(tmp_path, bad):
    with pytest.raises(JournalError):
        Journal(str(tmp_path), bad)
