"""Materialise weekly store/company payouts from the ledger."""

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from analytics import services


class Command(BaseCommand):
    help = "Create/refresh payout rows for a Monday-Sunday week (default: last week)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week",
            dest="week",
            help="Any ISO date in the week; normalised to its Monday",
        )

    def handle(self, *args, **options):
        day = parse_date(options["week"] or "") or services.report_date()
        period_start = services.week_start(day)
        payouts = services.materialise_payouts(period_start)

        self.stdout.write(
            self.style.SUCCESS(
                f"Materialised {len(payouts)} payout(s) for the week of {period_start}."
            )
        )
