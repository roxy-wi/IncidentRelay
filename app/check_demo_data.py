import ast
import sys
from pathlib import Path


def main():
    """
    Statically check important demo-data invariants.
    """

    manage_py = Path("manage.py").read_text(encoding="utf-8")
    tree = ast.parse(manage_py)

    source = manage_py

    checks = {
        "admin_detached_from_groups": 'detach_user_from_groups(admin)' in source,
        "create_admin_detaches_groups": 'detach_user_from_groups(user)' in source,
        "group_membership_created": 'groups_repo.add_user_to_group' in source,
        "active_group_set": 'users_repo.set_active_group' in source,
        "no_admin_role_string": 'role="admin"' not in source and "role='admin'" not in source,
        "rw_role_used": 'role="rw"' in source,
        "route_token_created": 'set_route_intake_token' in source,
    }

    failed = [name for name, ok in checks.items() if not ok]

    if failed:
        for name in failed:
            print(f"FAILED: {name}")
        return 1

    print("Demo data check OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
