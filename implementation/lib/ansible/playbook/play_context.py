# (c) 2026 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from typing import Any, Dict, Optional


class PlayContextAtomicExtension:
    """
    Mixin/Extension class for Ansible's PlayContext adding transaction mode configuration attributes.
    In upstream ansible-core, these fields integrate into lib/ansible/playbook/play_context.py.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Atomic transaction controls
        self.atomic: bool = kwargs.get("atomic", False)
        self.rollback_policy: str = kwargs.get("rollback_policy", "strict")  # "strict" or "best_effort"
        self.journal_storage: str = kwargs.get("journal_storage", "memory")  # "memory" or "persistent"
        self.journal_dir: Optional[str] = kwargs.get("journal_dir", None)
        self.current_checkpoint: Optional[str] = None

    def update_vars(self, play_vars: Dict[str, Any]) -> None:
        """Updates transaction flags from playbook keywords or extra-vars."""
        if "atomic" in play_vars:
            self.atomic = bool(play_vars["atomic"])
        if "rollback_policy" in play_vars:
            self.rollback_policy = str(play_vars["rollback_policy"]).lower()
        if "journal_storage" in play_vars:
            self.journal_storage = str(play_vars["journal_storage"]).lower()
        if "journal_dir" in play_vars:
            self.journal_dir = str(play_vars["journal_dir"])

    def set_checkpoint(self, checkpoint_name: str) -> None:
        self.current_checkpoint = checkpoint_name

    def clear_checkpoint(self) -> None:
        self.current_checkpoint = None
