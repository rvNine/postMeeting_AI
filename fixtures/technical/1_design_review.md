# Payment retry design review

The team agreed to move retry handling into the API layer because the worker swallowed errors. Sam will write the migration plan by 2026-10-02. Smaller batches reduced retry failures during the last test and should be used in the next migration rehearsal.
