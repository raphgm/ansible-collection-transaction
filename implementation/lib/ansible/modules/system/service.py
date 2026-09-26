# (c) 2026 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from typing import Any, Dict


def execute_service_module(
    module: Any,
    service_name: str,
    target_state: str,
    current_system_state: Dict[str, str],
) -> Dict[str, Any]:
    """
    Reference implementation of ansible.builtin.service with atomic compensation.
    Captures prior running/stopped state and registers compensating service command.
    """
    current_state = current_system_state.get(service_name, "stopped")
    changed = False

    if target_state == "restarted":
        changed = True
        # If restarted, compensation is to restore original state
        module.register_undo(
            module="ansible.builtin.service",
            action="set_state",
            parameters={
                "name": service_name,
                "state": current_state,
            },
        )
    elif target_state != current_state:
        changed = True
        module.register_undo(
            module="ansible.builtin.service",
            action="set_state",
            parameters={
                "name": service_name,
                "state": current_state,
            },
        )

    res = {
        "name": service_name,
        "state": target_state,
        "previous_state": current_state,
        "changed": changed,
        "failed": False,
    }
    return module.format_atomic_result(res)
