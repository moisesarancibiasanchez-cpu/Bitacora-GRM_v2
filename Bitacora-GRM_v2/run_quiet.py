"""
Wrapper to silence SQLAlchemy INFO logs and only show test output.
"""
import logging
import os
import sys
import io

# Suppress ALL SQLAlchemy logs
for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine",
             "sqlalchemy.pool", "sqlalchemy.orm"):
    logging.getLogger(name).setLevel(logging.CRITICAL + 1)

# Run the test
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

with open("test_picker_email_e2e.py") as f:
    code = f.read()

exec(compile(code, "test_picker_email_e2e.py", "exec"), {"__file__": "test_picker_email_e2e.py"})