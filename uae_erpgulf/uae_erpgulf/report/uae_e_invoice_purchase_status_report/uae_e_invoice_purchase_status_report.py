"""UAE E-Invoice Purchase Status Report (MOGAS fork: reads UAE E-Invoice Submission)."""

from uae_erpgulf.uae_erpgulf import report_utils


def execute(filters=None):
	filters = filters or {}
	return report_utils.get_columns("Purchase Invoice"), report_utils.get_data("Purchase Invoice", filters), None, None
