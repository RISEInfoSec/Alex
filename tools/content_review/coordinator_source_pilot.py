"""Run one bounded source-evidence cycle through the guarded coordinator.

This is a controlled test entry point, not an hourly scheduler or a claim of
review readiness. The existing stages retain the lease, decision fence,
request budgets, source workflow discovery and receipt contracts.
"""
from tools.content_review.coordinator_lifecycle import start
from tools.content_review.coordinator_source_cycle import source_pass


def run(repo,token,native,owner,run_id,*,begin=start,source=source_pass):
    started=begin(repo,token,native,owner,run_id)
    if not isinstance(started,dict):raise ValueError('Source pilot lease result invalid')
    if started.get('status')!='lease_started':return started
    return source(repo,token,native,started['review_head'],started['main_head'],owner,run_id)
