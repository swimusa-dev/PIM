"""ARC-05: one adapter per external system, each behind a small interface.

Source adapters:  read_changes(since) -> iterable of rows
Channel adapters: validate(payload), publish(batch), fetch_status(batch), fetch_errors(batch)
"""
