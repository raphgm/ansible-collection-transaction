#!/usr/bin/python
# Copyright: (c) 2026, Raphael Gab-Momoh
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = r"""
module: commit
short_description: Close a transaction and delete its saved files
description:
  - Call after every change and check has succeeded. After this, the transaction can no longer be rolled back.
options:
  id:
    description: Transaction name. Use different names to run independent transactions on one host.
    type: str
    default: default
  journal_dir:
    description: Directory on the managed host that holds journals and saved files.
    type: str
    default: /var/lib/ansible-transaction
  keep_journal:
    description: Keep journal.json (marked committed) for auditing. Saved file copies are always deleted.
    type: bool
    default: false
author: Raphael Gab-Momoh (@raphgm)
"""

EXAMPLES = r"""
- raphgm.transaction.commit:
"""

RETURN = r"""
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.raphgm.transaction.plugins.module_utils.journal import (
    DEFAULT_JOURNAL_DIR, Journal, JournalError)

COMMON_ARGS = dict(id=dict(type="str", default="default"),
                   journal_dir=dict(type="str", default=DEFAULT_JOURNAL_DIR))


def main():
    module = AnsibleModule(argument_spec=dict(COMMON_ARGS, keep_journal=dict(type="bool", default=False)),
                           supports_check_mode=True)
    if module.check_mode:
        module.exit_json(changed=True)
    j = Journal(module.params["journal_dir"], module.params["id"])
    try:
        j.commit(keep=module.params["keep_journal"])
    except (JournalError, OSError) as e:
        module.fail_json(msg=str(e))
    module.exit_json(changed=True)


if __name__ == "__main__":
    main()
