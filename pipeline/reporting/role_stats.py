from collections import Counter

def compute_role_stats(all_user_roles: list[list[str]], target_keyword: str) -> dict:
    total_member_count = len(all_user_roles)
    users_with_no_roles = [r for r in all_user_roles if not r]
    users_with_roles = [r for r in all_user_roles if r]

    all_assigned_roles = [role for sublist in users_with_roles for role in sublist]
    overall_role_counts = Counter(all_assigned_roles)

    users_in_target = [r for r in users_with_roles if target_keyword in r]
    only_target_count = sum(1 for r in users_in_target if len(r) == 1)
    target_co_occurrence = Counter([role for sublist in users_in_target for role in sublist if role != target_keyword])

    return {
        "total_member_count": total_member_count,
        "users_with_roles": len(users_with_roles),
        "users_with_no_roles": len(users_with_no_roles),
        "overall_role_counts": overall_role_counts,
        "users_in_target": len(users_in_target),
        "only_target_count": only_target_count,
        "target_co_occurrence": target_co_occurrence
    }