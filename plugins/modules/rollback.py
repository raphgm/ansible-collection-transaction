#!/usr/bin/python
# Copyright: (c) 2026, Raphael Gab-Momoh
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = r"""
module: rollback
short_description: Put everything recorded in a transaction back the way it was
description:
  - Restores files and packages newest-first, then services, so services restart on the old config.
  - Keeps going when one item fails and reports every failure at the end.
  - Safe to run again, and works from a later run if the controller died mid-play.
options:
  id:
    description: Transaction name. Use different names to run independent transactions on one host.
    type: str
    default: default
  journal_dir:
    description: Directory on the managed host that holds journals and saved files.
    type: str
    default: /var/lib/ansible-transaction
  restart_services:
    description: Restart (not just start) services that were running, so they reload restored config.
    type: bool
    default: true
author: Raphael Gab-Momoh (@raphgm)
notes:
  - Package downgrades need the old version to still be available from a repository or local cache.
  - Changes made by M(ansible.builtin.command), M(ansible.builtin.shell) or anything not snapshotted are not undone.
"""

EXAMPLES = r"""
- raphgm.transaction.rollback:
"""

RETURN = r"""
restored:
  description: Resources that were changed back.
  type: list
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.raphgm.transaction.plugins.module_utils.journal import (
    DEFAULT_JOURNAL_DIR, Journal, JournalError)

COMMON_ARGS = dict(id=dict(type="str", default="default"),
                   journal_dir=dict(type="str", default=DEFAULT_JOURNAL_DIR))


def main():
    module = AnsibleModule(argument_spec=dict(COMMON_ARGS, restart_services=dict(type="bool", default=True)),
                           supports_check_mode=False)
    j = Journal(module.params["journal_dir"], module.params["id"], runner=lambda cmd: module.run_command(cmd))
    try:
        restored, errors = j.rollback(restart_services=module.params["restart_services"])
    except (JournalError, OSError) as e:
        module.fail_json(msg=str(e))
    if errors:
        module.fail_json(msg="rollback incomplete: " + "; ".join(errors), restored=restored, errors=errors)
    module.exit_json(changed=bool(restored), restored=restored)


if __name__ == "__main__":
    main()
