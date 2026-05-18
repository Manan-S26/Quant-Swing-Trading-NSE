"""Dashboard support package.

Provides DashboardSession (data model) and DashboardSessionWriter (file I/O)
so that any engine component can write a JSON session file that the Streamlit
dashboard script reads.  No Streamlit imports here.
"""

from __future__ import annotations
