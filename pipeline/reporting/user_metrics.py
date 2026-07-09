import csv
import io
import itertools
from collections import Counter


def generate_user_roles_csv(user_data_rows: list[list[str]]) -> str:
    """Transforms raw discord member lists into a formatted CSV report."""
    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer)
    csv_writer.writerow(["User ID", "Username", "Display Name", "Roles"])
    csv_writer.writerows(user_data_rows)
    return csv_buffer.getvalue()


def generate_user_acquisition_csv(join_dates: Counter) -> str:
    """Transforms raw join timestamps into a cumulative growth CSV report."""
    sorted_months = sorted(join_dates.keys())
    cumulative_counts = list(itertools.accumulate([join_dates[m] for m in sorted_months]))

    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer)
    csv_writer.writerow(["Join Month (YYYY-MM)", "New Users This Month", "Total Users by End of Month"])

    for i, month in enumerate(sorted_months):
        csv_writer.writerow([month, join_dates[month], cumulative_counts[i]])

    return csv_buffer.getvalue()