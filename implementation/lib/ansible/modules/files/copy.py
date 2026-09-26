# (c) 2026 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import os
from typing import Any, Dict


def execute_copy_module(module: Any, src: str, dest: str, content: str) -> Dict[str, Any]:
    """
    Simulated implementation of ansible.builtin.copy leveraging AnsibleAtomicModuleMixin.
    """
    changed = False
    dest_existed = os.path.exists(dest)
    snapshot_path = None

    if dest_existed:
        with open(dest, "r", encoding="utf-8") as f:
            old_content = f.read()

        if old_content != content:
            changed = True
            # Snapshot original file into atomic journal
            snapshot_path = module.stage_file_snapshot(dest)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(content)

            # Register compensation to restore backup
            module.register_undo(
                module="ansible.builtin.copy",
                action="restore_snapshot",
                parameters={
                    "src": snapshot_path,
                    "dest": dest,
                },
            )
    else:
        changed = True
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

        # File was newly created; compensation is to remove it
        module.register_undo(
            module="ansible.builtin.file",
            action="delete",
            parameters={"path": dest},
        )

    res = {
        "dest": dest,
        "changed": changed,
        "failed": False,
        "msg": "File updated successfully" if changed else "File already in desired state",
    }
    return module.format_atomic_result(res)
