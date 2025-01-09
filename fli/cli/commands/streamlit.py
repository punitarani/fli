"""App command implementation."""

import sys
from pathlib import Path

import streamlit.web.cli as stcli


def streamlit() -> None:
    """Launch the Streamlit app interface."""
    # Get the path to main.py
    app_path = Path(__file__).parents[2].joinpath("app", "main.py")

    # Run the Streamlit app
    sys.argv = ["streamlit", "run", str(app_path), "--server.port", "3600"]
    sys.exit(stcli.main())
