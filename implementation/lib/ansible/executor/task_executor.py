# (c) 2026 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from implementation.lib.ansible.executor.rollback_manager import (
    AnsibleRollbackError,
    RollbackManager,
    RollbackPolicy,
)
from implementation.lib.ansible.playbook.play_context import PlayContextAtomicExtension

logger = logging.getLogger("ansible.executor.task_executor")


class TaskExecutorAtomicMixin:
    """
    Mixin integrated into TaskExecutor (lib/ansible/executor/task_executor.py)
    governing atomic transaction tracking and automated compensation upon task failure.
    """

    def __init__(
        self,
        play_context: PlayContextAtomicExtension,
        rollback_manager: Optional[RollbackManager] = None,
        **kwargs: Any,
    ) -> None:
        self._play_context = play_context
        self._rollback_manager = rollback_manager or RollbackManager(
            policy=RollbackPolicy(getattr(play_context, "rollback_policy", "strict"))
        )

    @property
    def rollback_manager(self) -> RollbackManager:
        return self._rollback_manager

    def execute_atomic_task(
        self,
        host_name: str,
        task_name: str,
        task_uuid: str,
        action_name: str,
        task_args: Dict[str, Any],
        module_invoker: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Executes a task under atomic transaction semantics:
        1. Handles explicit transaction control tasks ('checkpoint', 'rollback_to').
        2. Dispatches task execution via module_invoker.
        3. If mutation occurred ('changed'=True), records entry in host transaction journal.
        4. If failure occurred ('failed'=True), automatically initiates rollback compensation.
        """
        is_atomic = getattr(self._play_context, "atomic", False)

        # 1. Handle explicit transaction keywords
        if action_name in ("ansible.builtin.checkpoint", "checkpoint"):
            checkpoint_name = task_args.get("name", "checkpoint")
            self._rollback_manager.record_checkpoint(host_name, checkpoint_name)
            return {
                "changed": False,
                "msg": f"Transaction checkpoint '{checkpoint_name}' established for {host_name}",
            }

        if action_name in ("ansible.builtin.rollback_to", "rollback_to"):
            target_checkpoint = task_args.get("checkpoint")
            success = self._rollback_manager.rollback_host(host_name, checkpoint=target_checkpoint)
            return {
                "changed": True,
                "rolled_back": True,
                "success": success,
                "msg": f"Rolled back to checkpoint '{target_checkpoint}' for {host_name}",
            }

        # 2. Forward Execution
        try:
            result = module_invoker()
        except Exception as e:
            result = {"failed": True, "msg": str(e), "exception": repr(e)}

        if not is_atomic:
            return result

        # 3. Handle Mutations
        if result.get("changed", False):
            checkpoint_tag = getattr(self._play_context, "current_checkpoint", None)
            self._rollback_manager.register_task_mutation(
                host_name=host_name,
                task_name=task_name,
                task_uuid=task_uuid,
                result=result,
                checkpoint=checkpoint_tag,
            )

        # 4. Handle Failures & Trigger Automated Rollback
        if result.get("failed", False):
            logger.error(
                f"Task '{task_name}' failed on host '{host_name}'. Initiating compensating rollback."
            )
            rollback_ok = self._rollback_manager.rollback_host(host_name)
            result["_ansible_rolled_back"] = rollback_ok
            result["_ansible_transaction_recap"] = self._rollback_manager.get_recap_summary().get(host_name)

        return result
