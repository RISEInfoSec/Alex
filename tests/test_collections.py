"""Membership, metadata, generation and artifact regressions; all offline."""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from alex.collections import BASE, PAGE_SIZE, build, generate, load_editorial, pagination, route, select_collections, source_collections
from alex.pipelines import publish
from alex.taxonomy import CATEGORIES, INVESTIGATION_TYPES
from scripts.check_seo import check
from scripts.stage_site import stage

ROOT = Path(__file__).resolve().parents[1]


def papers(count=61):
    return [{"id": n + 1, "title": f"Paper {n:03d} <evidence>", "author": 'A & B',
             "year": 2020.0 + n % 5, "category": "OSINT Methodology",
             "investigation_type": "Phishing Analysis" if n % 2 == 0 else "Other",
             "doi": f"10.1234/test{n}", "source_url": f"https://example.org/{n}",
             "summary": "An original abstract", "venue": "Original venue"} for n in range(count)]


def soup(outputs, path):
    return BeautifulSoup(outputs[path + "index.html"], "html.parser")


def test_taxonomy_preserves_classifier_schema():
    from alex.pipelines.classify import CLASSIFICATION_SCHEMA
    assert CLASSIFICATION_SCHEMA["properties"]["Category"]["enum"] == CATEGORIES
    assert CLASSIFICATION_SCHEMA["properties"]["Investigation_Type"]["enum"] == INVESTIGATION_TYPES
    assert len(CATEGORIES) == 15 and len(INVESTIGATION_TYPES) == 11


def test_dimensions_membership_counts_and_pagination(collection_site):
    source = papers()
    output = build(collection_site, source)
    category = soup(output, "research/categories/osint-methodology/")
    second = soup(output, "research/categories/osint-methodology/page/2/")
    investigation = soup(output, "research/investigations/phishing-analysis/")
    assert len(category.select("li.paper")) == PAGE_SIZE
    assert len(second.select("li.paper")) == 11
    assert len(investigation.select("li.paper")) == 31
    expected = {p["title"] for p in source if p["investigation_type"] == "Phishing Analysis"}
    assert {h.get_text() for h in investigation.select("li.paper h3")} == expected
    assert second.select_one('link[rel="canonical"]')["href"] == BASE + "research/categories/osint-methodology/page/2/"
    assert category.select_one('a[href="/research/categories/osint-methodology/page/2/"]')
    assert second.select_one('a[href="/research/categories/osint-methodology/"]')
    assert second.select_one('ol')["start"] == "51"
    assert '2024.0' not in category.get_text() and '2024' in category.get_text()
    assert "<evidence>" in category.get_text() and category.find("evidence") is None
    assert not category.find_all("script", src=True)


def test_real_accepted_membership_is_exact_across_all_pages():
    output = build(ROOT)
    with (ROOT / "data/accepted_classified.csv").open(newline="", encoding="utf-8") as f:
        accepted = list(csv.DictReader(f))
    for collection in load_editorial(ROOT):
        field = {"category": "Category", "investigation_type": "Investigation_Type"}[collection["dimension"]]
        expected = sorted(r["title"] for r in accepted if r[field] == collection["value"])
        path = route(collection)
        actual = []
        for filename, html in output.items():
            if filename.startswith(path):
                actual.extend(h.get_text() for h in BeautifulSoup(html, "html.parser").select("li.paper h3"))
        assert sorted(actual) == expected


def test_schema_describes_only_visible_bibliography(collection_site):
    output = build(collection_site, papers())
    for path, raw in output.items():
        if not path.endswith(".html"):
            continue
        page = BeautifulSoup(raw, "html.parser")
        data = json.loads(page.select_one('script[type="application/ld+json"]').string)
        assert data["@type"] == "CollectionPage"
        if "mainEntity" not in data:
            continue
        items = data["mainEntity"]
        visible = page.select("li.paper h3")
        assert items["numberOfItems"] == len(visible) == len(items["itemListElement"])
        for item, heading in zip(items["itemListElement"], visible):
            assert item["name"] == heading.get_text()
            assert item["url"] == heading.a["href"]


def test_empty_small_and_identical_memberships_are_omitted(collection_site):
    editorial = load_editorial(collection_site)
    assert not select_collections([], editorial)[0]
    assert not select_collections(papers(4), editorial)[0]
    source = papers(10)
    for p in source:
        p["investigation_type"] = "Phishing Analysis"
    active, notes = select_collections(source, editorial)
    assert len(active) == 1 and any("identical membership" in note for note in notes)
    # Overlap below identity preserves both dimensions and reports high overlap.
    source[0]["investigation_type"] = "Other"
    active, notes = select_collections(source, editorial)
    assert len(active) == 2 and any("90%" in note for note in notes)
    output = build(collection_site, [])
    assert set(output) == {"research/index.html", "research/coverage.json", "sitemap.xml"}
    assert "No topic bibliographies" in output["research/index.html"]
    assert '/research/bibliography/' not in output["research/index.html"]


@pytest.mark.parametrize("change", [
    {"slug": "../escape"}, {"slug": "OSINT"}, {"value": "Invented category"},
    {"value": "Other"}, {"dimension": "tag"}, {"intro": ""}, {"related": ["categories/missing"]},
])
def test_invalid_editorial_fails_before_writing(collection_site, change):
    path = collection_site / "config/research_collections.json"
    config = json.loads(path.read_text())
    config["collections"][0].update(change)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        generate(collection_site, papers())
    assert not (collection_site / "research").exists()


def test_duplicate_routes_and_metadata_are_rejected(collection_site):
    path = collection_site / "config/research_collections.json"
    config = json.loads(path.read_text())
    config["collections"].append(config["collections"][0])
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Duplicate"):
        load_editorial(collection_site)


def test_duplicate_metadata_is_rejected(collection_site):
    path = collection_site / "config/research_collections.json"
    config = json.loads(path.read_text())
    config["collections"][1]["title"] = config["collections"][0]["title"]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="titles must be unique"):
        load_editorial(collection_site)


def test_record_metadata_provenance_and_unsafe_links(collection_site):
    source = papers(10)
    record = source[0]
    record.update(author="", year="", apwg_year="2025", retrieved="2026-10-27", doi="", link="javascript:alert(1)",
                  source_url='data:text/html,unsafe', collection_source="APWG.org eCrimes Research",
                  collection_url="https://ecrimeresearch.org/", venue="Actual publication venue")
    output = build(collection_site, source)
    page = soup(output, "research/categories/osint-methodology/")
    paper = next(li for li in page.select("li.paper") if record["title"] in li.get_text())
    assert "Author metadata incomplete" in paper.get_text()
    assert "Publication year not recorded" in paper.get_text()
    assert "2025" not in paper.get_text() and "2026-10-27" not in paper.get_text()
    assert "Collection: APWG.org eCrimes Research" in paper.get_text()
    assert "Actual publication venue" in paper.get_text()
    assert all(not a["href"].startswith(("data:", "javascript:")) for a in paper.select("a"))


def test_determinism_regeneration_and_obsolete_page_cleanup(collection_site):
    source = papers(121)
    output = build(collection_site, source)
    reversed_source = list(reversed(source))
    for i, p in enumerate(reversed_source):
        p["id"] = i + 9000
    assert output == build(collection_site, reversed_source)
    generate(collection_site, source)
    generate(collection_site, source, check=True)
    generate(collection_site, papers(20))
    assert not (collection_site / "research/categories/osint-methodology/page/2/index.html").exists()
    assert "page/2/" not in (collection_site / "sitemap.xml").read_text()
    (collection_site / "research/index.html").write_text("stale")
    with pytest.raises(ValueError, match="Regenerate"):
        generate(collection_site, papers(20), check=True)


def test_publish_regenerates_counts_without_changing_accepted_records(collection_site, monkeypatch):
    data = collection_site / "data"
    data.mkdir()
    source = papers(51)
    rows = [{"title": p["title"], "authors": p["author"], "year": p["year"], "doi": p["doi"],
             "Category": p["category"], "Investigation_Type": p["investigation_type"]} for p in source]
    accepted = data / "accepted_classified.csv"
    pd.DataFrame(rows).to_csv(accepted, index=False)
    original = accepted.read_bytes()
    monkeypatch.setattr("alex.utils.io.ROOT", collection_site)
    publish.run()
    assert accepted.read_bytes() == original
    assert "51 papers" in (collection_site / "research/categories/osint-methodology/index.html").read_text()
    assert (collection_site / "research/categories/osint-methodology/page/2/index.html").exists()
    pd.DataFrame(rows[:20]).to_csv(accepted, index=False)
    publish.run()
    assert "20 papers" in (collection_site / "research/categories/osint-methodology/index.html").read_text()
    assert not (collection_site / "research/categories/osint-methodology/page/2/index.html").exists()


def test_both_pages_workflows_use_tested_staging_and_keep_deploy_controls():
    pages = (ROOT / ".github/workflows/pages.yml").read_text()
    pipeline = (ROOT / ".github/workflows/pipeline.yml").read_text()
    assert "group: pages\n  cancel-in-progress: true" in pages
    for workflow in (pages, pipeline):
        assert "ref: main" in workflow
        assert "python3 scripts/stage_site.py" in workflow
        assert "path: _site" in workflow
    for filename in ("publish.yml", "pipeline.yml", "rebuild_site.yml", "apwg_approved_release.yml"):
        workflow = (ROOT / ".github/workflows" / filename).read_text()
        assert "git add -A research sitemap.xml" in workflow


def test_apwg_network_audits_are_manual_only():
    workflow = (ROOT / ".github/workflows/apwg_import_tests.yml").read_text()
    audit = workflow.split("  live_source_audit:", 1)[1].split("  classification_review:", 1)[0]
    review = workflow.split("  classification_review:", 1)[1]
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in audit
    assert "if: ${{ github.event_name == 'workflow_dispatch' &&" in review
    assert "  pull_request:" in workflow and "  test:" in workflow


def test_editorial_covers_every_named_controlled_taxonomy_value():
    editorial = load_editorial(ROOT)
    assert {c["value"] for c in editorial if c["dimension"] == "category"} == set(CATEGORIES) - {"Other"}
    assert {c["value"] for c in editorial if c["dimension"] == "investigation_type"} == set(INVESTIGATION_TYPES) - {"Other"}
    for field in ("intro", "scope", "use", "summary"):
        assert len({c[field] for c in editorial}) == len(editorial)


def test_complete_bibliography_covers_all_sources_and_miscellaneous_records():
    records = json.loads((ROOT / "data/papers.json").read_text())
    output = build(ROOT)
    visible = []
    for path, raw in output.items():
        if path.startswith("research/bibliography/") and path.endswith(".html"):
            visible.extend(h.get_text() for h in BeautifulSoup(raw, "html.parser").select("li.paper h3"))
    assert Counter(visible) == Counter(p["title"] for p in records)
    # This assertion explicitly includes records from every source and both-Other.
    for record in records:
        assert record["title"] in visible
    report = json.loads(output["research/coverage.json"])
    assert report["total_papers"] == report["complete_bibliography_records"] == len(records)
    expected_miscellaneous = sum(p["category"] == "Other" and p["investigation_type"] == "Other" for p in records)
    assert report["complete_bibliography_only_records"] == expected_miscellaneous
    assert report["topic_collections"] == len(load_editorial(ROOT))
    assert len(report["taxonomy"]) == len(CATEGORIES) + len(INVESTIGATION_TYPES)
    assert all(row["path"] is None for row in report["taxonomy"] if row["value"] == "Other")
    assert not any('/other/' in path for path in output)


def test_collection_membership_never_filters_by_source(collection_site):
    records = papers(12)
    records[0]["collection_source"] = "APWG.org eCrimes Research"
    records[1]["collection_source"] = "Independent research archive"
    records[2]["collection_source"] = ""
    output = build(collection_site, records)
    page = soup(output, "research/categories/osint-methodology/")
    assert Counter(h.get_text() for h in page.select('li.paper h3')) == Counter(p["title"] for p in records)
    assert "APWG.org eCrimes Research" in page.get_text()
    assert "Independent research archive" in page.get_text()


def test_miscellaneous_only_corpus_keeps_every_record_without_topic_stubs(collection_site):
    records = papers(4)
    for paper in records:
        paper["category"] = paper["investigation_type"] = "Other"
    output = build(collection_site, records)
    assert set(output) == {'research/index.html', 'research/bibliography/index.html', 'research/coverage.json', 'sitemap.xml'}
    report = json.loads(output['research/coverage.json'])
    assert report['complete_bibliography_only_records'] == 4
    assert len(soup(output, 'research/bibliography/').select('li.paper')) == 4
    assert 'Research category: Other' in soup(output, 'research/bibliography/').get_text()


def test_large_bibliography_pagination_is_bounded_and_has_crawlable_neighbors():
    complete = {'dimension': 'corpus'}
    for current in (1, 2, 36, 71, 72):
        page = BeautifulSoup(pagination(complete, current, 72), 'html.parser')
        assert len(page.select('a')) <= 8
        assert page.select_one('[aria-current="page"]').get_text() == f'Page {current}'
        if current > 1:
            assert page.find('a', string='Previous')['href'] == '/' + route(complete, current - 1)
        if current < 72:
            assert page.find('a', string='Next')['href'] == '/' + route(complete, current + 1)
        assert not any('?page=' in a['href'] for a in page.select('a'))


def test_every_static_bibliography_page_is_reachable_from_hub():
    output = build(ROOT)
    expected = {path for path in output if path.endswith('.html')}
    visited, pending = set(), ['research/index.html']
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        page = BeautifulSoup(output[path], 'html.parser')
        for link in page.select('a[href]'):
            href = link['href'].split('#', 1)[0]
            if not href.startswith('/research/'):
                continue
            target = href.lstrip('/') + ('index.html' if href.endswith('/') else '')
            if target in expected and target not in visited:
                pending.append(target)
    assert visited == expected


def test_source_collection_bibliography_matches_explicit_provenance():
    records = json.loads((ROOT / 'data/papers.json').read_text())
    output = build(ROOT)
    group = next(g for g in source_collections(ROOT, records) if g['label'] == 'APWG.org eCrimes Research')
    titles = []
    for path, raw in output.items():
        if path.startswith(route(group)) and path.endswith('.html'):
            page = BeautifulSoup(raw, 'html.parser')
            titles.extend(h.get_text() for h in page.select('li.paper h3'))
    assert Counter(titles) == Counter(p['title'] for p in records if p.get('collection_source') == 'APWG.org eCrimes Research')
    assert soup(output, 'research/').find('a', href='/research/collections/apwg-ecrime/')
    assert soup(output, 'research/collections/apwg-ecrime/').find('a', href='https://ecrimeresearch.org/ecrime-research-papers')


def test_prepared_sources_link_to_original_archive_without_empty_pages(collection_site):
    output = build(collection_site, papers(10))
    hub = soup(output, 'research/')
    source_section = hub.select_one('#source-collections')
    assert source_section.find('a', string='SOUPS')['href'] == 'https://soups.page/'
    assert 'No papers accepted into ALEX yet' in source_section.get_text()
    assert not any(path.startswith('research/collections/') for path in output)
    assert 'Virus Bulletin' not in source_section.get_text()
    assert not any('/collections/' in line for line in output['sitemap.xml'].splitlines())


def test_future_approved_collection_appears_and_cleans_up_automatically(collection_site):
    records = papers(3)
    records[0]['collection_source'] = 'SOUPS (Symposium On Usable Privacy and Security) and USENIX (the Advanced Computing Systems Association)'
    records[0]['collection_url'] = 'https://soups.page/'
    records[0]['venue'] = 'Original publication venue'
    original = json.dumps(records, sort_keys=True)
    output = build(collection_site, records)
    path = 'research/collections/soups/index.html'
    assert path in output and 'research/collections/soups/' in output['sitemap.xml']
    assert len(BeautifulSoup(output[path], 'html.parser').select('li.paper')) == 1
    assert 'Original publication venue' in BeautifulSoup(output[path], 'html.parser').get_text()
    assert json.dumps(records, sort_keys=True) == original
    generate(collection_site, records)
    generate(collection_site, papers(3))
    assert not (collection_site / path).exists()
    assert 'research/collections/soups/' not in (collection_site / 'sitemap.xml').read_text()


def test_candidate_source_activates_only_from_collection_attribution(collection_site):
    records = papers(3)
    records[0]['venue'] = 'Virus Bulletin'
    output = build(collection_site, records)
    assert 'research/collections/virus-bulletin/index.html' not in output
    records[0]['collection_source'] = 'Virus Bulletin'
    output = build(collection_site, records)
    assert 'research/collections/virus-bulletin/index.html' in output
    assert soup(output, 'research/').find('a', href='/research/collections/virus-bulletin/')


def test_unprofiled_source_gets_original_links_without_boilerplate_page(collection_site):
    records = papers(3)
    records[0].update(collection_source='Another accepted archive', collection_url='https://example.org/archive')
    output = build(collection_site, records)
    hub = soup(output, 'research/')
    assert hub.find('a', string='Another accepted archive')['href'] == 'https://example.org/archive'
    assert not any(path.startswith('research/collections/') for path in output)
    report = json.loads(output['research/coverage.json'])
    entry = next(g for g in report['source_collections'] if g['label'] == 'Another accepted archive')
    assert entry['count'] == 1 and entry['path'] is None


@pytest.mark.parametrize('change', [
    {'slug': '../escape'}, {'archive_url': 'javascript:alert(1)'}, {'values': []},
    {'intro': ''}, {'show_when_empty': 'yes'}, {'values': ['SOUPS']},
])
def test_invalid_or_ambiguous_source_profiles_fail(collection_site, change):
    path = collection_site / 'config/research_collections.json'
    config = json.loads(path.read_text())
    config['source_collections'][0].update(change)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        build(collection_site, papers())


def test_actual_artifact_includes_all_pages_and_preserves_downloads(tmp_path):
    # Isolate staging; no network, deployment or source-corpus writes.
    for name in ("index.html", "robots.txt", "sitemap.xml"):
        shutil.copy2(ROOT / name, tmp_path / name)
    for name in ("assets", "config"):
        shutil.copytree(ROOT / name, tmp_path / name)
    (tmp_path / "data").mkdir()
    for name in ("accepted_classified.csv", "papers.json", "osint_cyber_papers.csv", "collection_status.json"):
        shutil.copy2(ROOT / "data" / name, tmp_path / "data" / name)
    stage(tmp_path, tmp_path / "_site")
    artifact = tmp_path / "_site"
    for path in build(tmp_path):
        assert (artifact / path).read_bytes() == (tmp_path / path).read_bytes()
    for name in ("papers.json", "osint_cyber_papers.csv", "collection_status.json"):
        assert (artifact / "data" / name).read_bytes() == (ROOT / "data" / name).read_bytes()
    assert not (artifact / "data/accepted_classified.csv").exists()
    assert not (artifact / "config").exists()
    # Stale artifacts are cleared and absent output pages are caught.
    (artifact / "research/stale.html").write_text("stale")
    stage(tmp_path, artifact)
    assert not (artifact / "research/stale.html").exists()
    (artifact / "research/categories/osint-methodology/index.html").unlink()
    with pytest.raises(AssertionError, match="Missing or stale"):
        check(artifact, source_root=tmp_path)
