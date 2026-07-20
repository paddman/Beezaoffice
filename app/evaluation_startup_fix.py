from __future__ import annotations

from evaluation_hardening import bootstrap_evaluator_identity
from main import app

# Main startup creates all SQLAlchemy tables. Keep the evaluator identity bootstrap
# after that schema initialization but immediately before the evaluator worker starts.
handlers = app.router.on_startup
while bootstrap_evaluator_identity in handlers:
    handlers.remove(bootstrap_evaluator_identity)

insert_at = len(handlers)
for index, handler in enumerate(handlers):
    if getattr(handler, "__name__", "") == "start_evaluator":
        insert_at = index
        break
handlers.insert(insert_at, bootstrap_evaluator_identity)
