# Ansible Transaction Journal Specification (ATJ-v1)

This document formalizes the schema and serialization format for journal entries recorded during an atomic Ansible playbook execution.

---

## 1. Schema Definition

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AnsibleTransactionJournal",
  "type": "object",
  "required": ["version", "play_uuid", "host", "created_at", "status", "entries"],
  "properties": {
    "version": { "type": "string", "enum": ["1.0"] },
    "play_uuid": { "type": "string", "format": "uuid" },
    "host": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "status": {
      "type": "string",
      "enum": ["ACTIVE", "COMMITTED", "ROLLING_BACK", "ROLLED_BACK", "ROLLBACK_FAILED"]
    },
    "entries": {
      "type": "array",
      "items": { "$ref": "#/$defs/JournalEntry" }
    }
  },
  "$defs": {
    "JournalEntry": {
      "type": "object",
      "required": ["entry_id", "task_name", "task_uuid", "timestamp", "undo_action"],
      "properties": {
        "entry_id": { "type": "integer" },
        "task_name": { "type": "string" },
        "task_uuid": { "type": "string", "format": "uuid" },
        "timestamp": { "type": "string", "format": "date-time" },
        "supports_atomic": { "type": "boolean" },
        "undo_action": {
          "type": "object",
          "required": ["module", "action", "parameters"],
          "properties": {
            "module": { "type": "string" },
            "action": { "type": "string" },
            "parameters": { "type": "object" },
            "requires_become": { "type": "boolean" },
            "become_user": { "type": "string" }
          }
        },
        "checkpoint": { "type": ["string", "null"] }
      }
    }
  }
}
```

---

## 2. Concrete Example

Below is an actual transaction journal recorded for a host mutating `/etc/nginx/nginx.conf` and updating a service:

```json
{
  "version": "1.0",
  "play_uuid": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "host": "web01.infra.internal",
  "created_at": "2026-09-26T10:00:00Z",
  "status": "ROLLING_BACK",
  "entries": [
    {
      "entry_id": 1,
      "task_name": "Install nginx package",
      "task_uuid": "3a0d5c41-9457-4ea2-8094-08f37fec39e1",
      "timestamp": "2026-09-26T10:00:05Z",
      "supports_atomic": true,
      "undo_action": {
        "module": "ansible.builtin.apt",
        "action": "remove_installed",
        "parameters": {
          "name": "nginx",
          "state": "absent",
          "purge": true
        },
        "requires_become": true,
        "become_user": "root"
      },
      "checkpoint": null
    },
    {
      "entry_id": 2,
      "task_name": "Deploy production nginx configuration",
      "task_uuid": "7b1e84a2-1134-4bcf-a821-4f11e9a4092b",
      "timestamp": "2026-09-26T10:00:12Z",
      "supports_atomic": true,
      "undo_action": {
        "module": "ansible.builtin.copy",
        "action": "restore_snapshot",
        "parameters": {
          "staging_path": "/tmp/.ansible_journal_f47ac10b/entry_2_nginx.conf.bak",
          "dest": "/etc/nginx/nginx.conf",
          "mode": "0644",
          "owner": 0,
          "group": 0
        },
        "requires_become": true,
        "become_user": "root"
      },
      "checkpoint": "pre_service_start"
    },
    {
      "entry_id": 3,
      "task_name": "Restart nginx service",
      "task_uuid": "993a408e-f19b-449e-bdf1-b841e21b790d",
      "timestamp": "2026-09-26T10:00:15Z",
      "supports_atomic": true,
      "undo_action": {
        "module": "ansible.builtin.systemd_service",
        "action": "restore_state",
        "parameters": {
          "name": "nginx",
          "state": "stopped",
          "enabled": false
        },
        "requires_become": true,
        "become_user": "root"
      },
      "checkpoint": null
    }
  ]
}
```
