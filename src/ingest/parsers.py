"""
Parsers for all four data sources.
Each parser normalizes raw data into ParsedRecord objects.
"""
from typing import List
from src.constants import SourceName, NodeType
from src.ingest.schemas import ParsedRecord, build_parsed_record


def parse_orders_db(data: dict) -> List[ParsedRecord]:
    """Parse orders_db.json format."""
    records = []
    nodes = data.get("nodes", {})
    order_node = nodes.get("order")
    if order_node:
        records.append(build_parsed_record(order_node, SourceName.ORDERS_DB))
    return records


def parse_razorpay_recon(data: dict) -> List[ParsedRecord]:
    """Parse razorpay_recon.json format — payment, fee, refunds, settlement."""
    records = []
    nodes = data.get("nodes", {})

    for key in ["payment", "fee", "settlement"]:
        node = nodes.get(key)
        if node:
            records.append(build_parsed_record(node, SourceName.RAZORPAY_RECON))

    # Refunds
    for ref in nodes.get("refunds", []):
        records.append(build_parsed_record(ref, SourceName.RAZORPAY_RECON))

    return records


def parse_bank_statement(data: dict) -> List[ParsedRecord]:
    """Parse bank_statement.json format — bank entries."""
    records = []
    nodes = data.get("nodes", {})

    for entry in nodes.get("bank_entries", []):
        records.append(build_parsed_record(entry, SourceName.BANK_STATEMENT))

    return records


def parse_tax_invoice(data: dict) -> List[ParsedRecord]:
    """Parse tax_invoice.json format — tax node."""
    records = []
    nodes = data.get("nodes", {})
    tax_node = nodes.get("tax")
    if tax_node:
        records.append(build_parsed_record(tax_node, SourceName.TAX_INVOICE))
    return records


def parse_ledger_entries(data: dict) -> List[ParsedRecord]:
    """Parse ledger postings from any source that includes them."""
    records = []
    nodes = data.get("nodes", {})

    for posting in nodes.get("ledger_postings", []):
        # Ledger entries come from various sources
        source_str = posting.get("source", "razorpay_recon")
        try:
            source = SourceName(source_str)
        except ValueError:
            source = SourceName.RAZORPAY_RECON
        records.append(build_parsed_record(posting, source))

    return records


def ingest_case(case_dict: dict) -> List[ParsedRecord]:
    """
    Ingest a single case dict (from batch JSON) through all parsers.
    Returns a flat list of ParsedRecord objects.
    """
    records = []
    records.extend(parse_orders_db(case_dict))
    records.extend(parse_razorpay_recon(case_dict))
    records.extend(parse_bank_statement(case_dict))
    records.extend(parse_tax_invoice(case_dict))
    records.extend(parse_ledger_entries(case_dict))
    return records
