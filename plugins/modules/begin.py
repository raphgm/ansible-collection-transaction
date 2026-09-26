#!/usr/bin/python
# Copyright: (c) 2026, Raphael Gab-Momoh
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = r"""
module: begin
short_description: Open a transaction on the managed host
description:
  - Creates an empty on-host journal. Later M(raphgm.transaction.snapshot) calls record state into it.
  - Fails if an earlier transaction with the same O(id) was never committed or rolled back,
    because that means a previous run died half way and the host may need a rollback.
options:
  id:
    description: Transaction name. Use different names to run independent transactions on one host.
    type: str
    default: default
  journal_dir:
    description: Directory on the managed host that holds journals and saved files.
    type: str
    default: /var/lib/ansible-transaction
  force:
    description: Discard a leftover open transaction instead of failing.
    type: bool
    default: false
author: Raphael Gab-Momoh (@raphgm)
"""

EXAMPLES = r"""
- raphgm.transaction.begin:
"""

RETURN = r"""
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.raphgm.transaction.plugins.module_utils.journal import (
    DEFAULT_JOURNAL_DIR, Journal, JournalError)

COMMON_ARGS = dict(id=dict(type="str", default="default"),
                   journal_dir=dict(type="str", default=DEFAULT_JOURNAL_DIR))


def main():
    module = AnsibleModule(argument_spec=dict(COMMON_ARGS, force=dict(type="bool", default=False)),
                           supports_check_mode=True)
    j = Journal(module.params["journal_dir"], module.params["id"])
    if module.check_mode:
        module.exit_json(changed=True, transaction_id=j.txn_id)
    try:
        j.begin(force=module.params["force"])
    except (JournalError, OSError) as e:
        module.fail_json(msg=str(e))
    module.exit_json(changed=True, transaction_id=j.txn_id, journal=j.root)


if __name__ == "__main__":
    main()
