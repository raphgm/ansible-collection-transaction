# (c) 2026 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Dict, Optional


class AnsibleAtomicModuleMixin:
    """
    Mixin added to AnsibleModule in lib/ansible/module_utils/basic.py
    enabling modules to capture pre-state and return deterministic compensating undo payloads.
    """

    def init_atomic(self, supports_atomic: bool = False) -> None:
        self.supports_atomic: bool = supports_atomic
        self._undo_action: Optional[Dict[str, Any]] = None
        self._staging_journal_dir: Optional[str] = os.environ.get("ANSIBLE_JOURNAL_STAGING_DIR")

    def register_undo(
        self,
        module: str,
        action: str,
        parameters: Dict[str, Any],
        requires_become: bool = False,
        become_user: Optional[str] = None,
    ) -> None:
        """
        Registers the reverse operation required to undo this module's mutation.
        """
        self._undo_action = {
            "module": module,
            "action": action,
            "parameters": parameters,
            "requires_become": requires_become,
            "become_user": become_user,
        }

    def stage_file_snapshot(self, path: str) -> Optional[str]:
        """
        Safely copies the target file to the transaction journal staging directory before modification.
        Uses hardlinks when on the same filesystem for zero-cost snapshotting.
        """
        if not os.path.exists(path):
            return None

        staging_dir = self._staging_journal_dir or tempfile.gettempdir()
        os.makedirs(staging_dir, exist_ok=True)

        filename = os.path.basename(path)
        snapshot_dest = os.path.join(staging_dir, f"{filename}.bak_{os.getpid()}")

        try:
            # Attempt instant hardlink
            os.link(path, snapshot_dest)
        except OSError:
            # Fallback to copy preserving mode and ownership
            shutil.copy2(path, snapshot_dest)

        return snapshot_dest

    def format_atomic_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Injects atomic metadata into the final module response sent to controller."""
        result["_ansible_supports_atomic"] = self.supports_atomic
        if self._undo_action:
            result["_ansible_undo"] = self._undo_action
        return result
