#!/usr/bin/python
# Copyright: (c) 2026, Raphael Gab-Momoh
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = r"""
module: snapshot
short_description: Record the current state of files, packages and services
description:
  - Saves what a rollback needs to put things back as they are now.
  - Only the first snapshot of each resource in a transaction is kept, so calling
    this again later in the play never overwrites the original state.
options:
  id:
    description: Transaction name. Use different names to run independent transactions on one host.
    type: str
    default: default
  journal_dir:
    description: Directory on the managed host that holds journals and saved files.
    type: str
    default: /var/lib/ansible-transaction
  paths:
    description:
      - Files or symlinks to save. A path that does not exist yet is removed on rollback.
      - Directories that already exist are not supported.
    type: list
    elements: path
    default: []
  packages:
    description: Packages whose installed version (or absence) to record.
    type: list
    elements: str
    default: []
  services:
    description: systemd services whose active and enabled state to record.
    type: list
    elements: str
    default: []
  package_manager:
    description: Package manager to use.
    type: str
    choices: [auto, apt, dnf, yum]
    default: auto
author: Raphael Gab-Momoh (@raphgm)
"""

EXAMPLES = r"""
- raphgm.transaction.snapshot:
    paths: [/etc/app/app.conf]
    packages: [app-server]
    services: [app-server]
"""

RETURN = r"""
recorded:
  description: Resources recorded by this call (already-recorded ones are skipped).
  type: list
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.raphgm.transaction.plugins.module_utils.journal import (
    DEFAULT_JOURNAL_DIR, Journal, JournalError)

COMMON_ARGS = dict(id=dict(type="str", default="default"),
                   journal_dir=dict(type="str", default=DEFAULT_JOURNAL_DIR))


def main():
    module = AnsibleModule(argument_spec=dict(
        COMMON_ARGS,
        paths=dict(type="list", elements="path", default=[]),
        packages=dict(type="list", elements="str", default=[]),
        services=dict(type="list", elements="str", default=[]),
        package_manager=dict(type="str", default="auto", choices=["auto", "apt", "dnf", "yum"]),
    ), supports_check_mode=True)
    if module.check_mode:
        module.exit_json(changed=False, recorded=[])
    p = module.params
    j = Journal(p["journal_dir"], p["id"], runner=module.run_command)
    try:
        added = j.snapshot(p["paths"], p["packages"], p["services"], p["package_manager"])
    except (JournalError, OSError) as e:
        module.fail_json(msg=str(e))
    module.exit_json(changed=bool(added), recorded=["%s:%s" % (e["kind"], e["name"]) for e in added])


if __name__ == "__main__":
    main()
