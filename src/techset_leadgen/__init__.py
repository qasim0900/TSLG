"""Techset LeadGen: native PySide6 desktop application for LinkedIn outreach teams.

Layers (each a subpackage):

* ``desktop`` – the PySide6 windows, pages, dialogs, and theme (no business rules);
* ``services`` – authenticated workflows: every read/change checks permissions and audits;
* ``domain`` – vocabularies, status rules, and pure calculations;
* ``database`` – SQLAlchemy engine, ORM models, Alembic migrations, and the original SQLite tables;
* ``security`` – passwords, tokens, and the role/permission matrix;
* ``reports`` and ``analytics`` – branded HTML reports and the retired sales analytics.
"""

from techset_leadgen.branding import PRODUCT_VERSION as __version__

__all__ = ["__version__"]
