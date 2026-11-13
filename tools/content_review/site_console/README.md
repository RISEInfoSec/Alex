# Review-console status source

These are the repository-controlled Site status modules and focused tests.
Deploy the files under `lib/` to the matching paths in the Sites source checkout
using the supported Sites source workflow. Preserve the Site's access policy.
Run `node --test tools/content_review/site_console/tests/*.test.mjs` here and
the Site's own test suite before publishing. The heartbeat and worker state
are repository evidence; they do not independently authenticate native
scheduler outcomes or establish candidate processing.
