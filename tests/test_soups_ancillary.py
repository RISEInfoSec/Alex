from alex.pipelines.soups_ancillary import parse_page


def test_new_and_republished_posters_are_separate():
    html = '''<h3>Novel Posters</h3><ul><li><a href="a.pdf">A novel paper</a>
    <ul class="author-list"><li>A. Person, <em>A University</em></li></ul></li></ul>
    <h3>Posters of Previously Published Work</h3><ul><li><a href="b.pdf">An older paper</a>
    <ul class="author-list"><li>B. Person, <em>B University</em></li></ul></li></ul>'''
    rows = parse_page(html, 'https://soups.page/2026/postersproc.html')
    assert [r['document_type'] for r in rows] == ['poster_extended_abstract', 'poster_of_previously_published_work']
    assert rows[0]['authors'] == 'A. Person'
    assert rows[1]['publication_year_status'] == 'original_venue_year_pending'
    assert all(not r['publication_approved'] for r in rows)


def test_earlier_usenix_paragraph_posters_preserve_section():
    html = '''<h2>Unpublished Work</h2><p><strong>Original study</strong><br>
    A. Person, <em>University</em><br><a href="/a.pdf">Poster description PDF</a></p>
    <h2>Published Work</h2><p><strong>Existing study</strong><br>B. Person<br>
    <a href="/b.pdf">Poster description PDF</a></p>'''
    rows = parse_page(html, 'https://www.usenix.org/conference/soups2018/poster-session')
    assert len(rows) == 2
    assert rows[0]['authors'] == 'A. Person'
    assert rows[1]['previously_published'] is True


def test_legacy_workshop_does_not_import_call_for_papers():
    html = '''<a href="cfp.pdf">Call for papers and participation</a>
    <a href="study.pdf">Research directions for intrusion recovery</a>'''
    rows = parse_page(html, 'https://cups.cs.cmu.edu/soups/2008/usm.html')
    assert len(rows) == 1
    assert rows[0]['document_type'] == 'workshop_paper_or_abstract'
    assert rows[0]['year'] == 2008
