"""Recompute daily rollups for a range of reporting days."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from analytics import services


class Command(BaseCommand):
    help = "Recompute DailyStoreStat/DailyProductStat (default: yesterday)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="from_date", help="ISO date, inclusive")
        parser.add_argument("--to", dest="to_date", help="ISO date, inclusive")

    def handle(self, *args, **options):
        yesterday = services.report_date() - timedelta(days=1)

        to_day = parse_date(options["to_date"] or "") or yesterday
        from_day = parse_date(options["from_date"] or "") or to_day
        if to_day < from_day:
            raise CommandError("--to must not be before --from.")

        touched = services.rollup_range(from_day, to_day)
        self.stdout.write(
            self.style.SUCCESS(f"Rolled up {from_day}..{to_day}: {touched} store-day(s).")
        )
