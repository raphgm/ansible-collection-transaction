# raphgm.transaction

Roll back an Ansible deploy automatically when it fails.

When a play fails half way through, the host is left half-changed: new config, old binary,
service down. Fixing that today means writing the undo logic by hand in `rescue:`.
This collection records the state of the things you name before the play touches them,
and puts them back automatically if any task or health check fails.

```yaml
- hosts: webservers
  become: true
  roles:
    - role: raphgm.transaction.atomic
      vars:
        atomic_paths: [/etc/nginx/conf.d/app.conf]
        atomic_packages: [nginx]
        atomic_services: [nginx]
        atomic_tasks: deploy.yml        # your normal tasks
        atomic_verify: healthcheck.yml  # optional; failing here also rolls back
```

If anything in `deploy.yml` or `healthcheck.yml` fails, the host gets back its original
config file, the original nginx version, and nginx in the state it was in before, restarted
on the old config. Then the play fails with a clear message saying what was restored.

## Try it in 30 seconds

No root and no remote host needed:

```bash
git clone https://github.com/raphgm/ansible-collection-transaction ansible_collections/raphgm/transaction
cd ansible_collections/raphgm/transaction
ANSIBLE_COLLECTIONS_PATH=../../.. ansible-playbook examples/demo.yml
cat /tmp/ansible-txn-demo/app.conf   # still version=1: the bad deploy was undone
```

## What it can restore

| Resource | Recorded | Restored on rollback |
| --- | --- | --- |
| File | content, mode, owner, or "did not exist" | original file put back; new files removed |
| Symlink | target | original target |
| Package (apt, dnf, yum) | installed version, or "not installed" | downgraded or removed |
| systemd service | running or not, enabled or not | put back, then restarted so it loads the restored config |

Files and packages are restored newest first, then services, so a service never
restarts on a half-restored system.

## What it cannot restore

Be honest with yourself about these before relying on it:

- **Anything you didn't list.** It only restores what you pass to `atomic_paths`,
  `atomic_packages` and `atomic_services`.
- **`command` / `shell` side effects**, such as database migrations. Run those last, or
  make them backward compatible.
- **Package downgrades need the old version to still be downloadable.** apt usually keeps
  it in the cache; many repos drop old versions.
- **Existing directories.** Snapshot the files inside them instead. A directory that
  doesn't exist yet is fine: it is removed on rollback.
- **Remote systems.** Cloud resources, load balancers and APIs are out of scope.

## Using the modules directly

The role is a thin wrapper. You can use the modules in your own `block`/`rescue`:

```yaml
- raphgm.transaction.begin:

- block:
    - raphgm.transaction.snapshot:
        paths: [/etc/app/app.conf]
        services: [app]
    - ansible.builtin.template: {src: app.conf.j2, dest: /etc/app/app.conf}
    - ansible.builtin.systemd_service: {name: app, state: restarted}
    - raphgm.transaction.commit:
  rescue:
    - raphgm.transaction.rollback:
    - ansible.builtin.fail: {msg: "Deploy failed and was rolled back"}
```

You can call `snapshot` again half way through a play. Only the first snapshot of each
item counts, so the original state is never overwritten.

## If the controller dies mid-deploy

The journal is stored on the managed host (`/var/lib/ansible-transaction/<id>/`), not on
the controller. If your laptop or CI runner dies half way, the next run's `begin` refuses
to start and tells you. Then either roll back:

```bash
ansible webservers -b -m raphgm.transaction.rollback
```

or discard the old transaction with `force: true` (`atomic_force: true` in the role).

## Roadmap

- Snapshot automatically from the tasks themselves, so no need to list paths
  (for example an action plugin that wraps `template`, `copy` and `lineinfile`).
- `lineinfile` / `blockinfile` / `ini_file` without full file copies.
- A small hook in `ansible-core` that would make this work with no list at all. The
  design is in [docs/design.md](docs/design.md). This collection is the proof of concept for it.

Feedback and bug reports are welcome in [issues](https://github.com/raphgm/ansible-collection-transaction/issues).

## Development

```bash
pip install ansible-core pytest
mkdir -p /tmp/ac/ansible_collections/raphgm && ln -s "$PWD" /tmp/ac/ansible_collections/raphgm/transaction
cd /tmp/ac/ansible_collections/raphgm/transaction && PYTHONPATH=/tmp/ac pytest tests/unit
```

CI runs `ansible-test sanity`, the unit tests, the demo, and a real nginx rollback test.

License: GPL-3.0-or-later
