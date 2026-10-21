"""Accounts, permissions, audit trail, and record workflows for Techset LeadGen.

Pure Python with no user-interface code. It works on the application's single
SQLite database (the same file the analytics use); the PySide6 screens call
these services, which enforce roles, validation, and auditing.
"""
