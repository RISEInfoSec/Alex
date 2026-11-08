from tools.content_review.coordinator_git_preflight import run


def info(exhausted=False):
    return {'visible_processes':12,'zombies':3,'same_uid_processes':12,'unreadable_processes':0,
            'cgroup_current':15,'cgroup_max':100,'user_soft_limit':200,'capacity_exhausted':exhausted}


def test_preflight_reads_refs_once_without_claiming_processing():
    calls=[];times=iter([1,1.5,2])
    result=run('.',capacity_reader=info,heads=lambda repo:(calls.append('heads') or {'verified':'refs'}),
               fetch=lambda repo,refs,run_id:calls.append(('fetch',refs,run_id)),clock=lambda:next(times))
    assert result['status']=='ready' and result['refs_verified'] is True and result['candidate_processing'] is False
    assert result['read_heads_ms']==500 and result['fetch_heads_ms']==500
    assert calls==['heads',('fetch',{'verified':'refs'},'git-preflight')]


def test_exhausted_capacity_stops_before_any_git_access():
    calls=[];result=run('.',capacity_reader=lambda:info(True),heads=lambda *a:calls.append('heads'))
    assert result['status']=='blocked' and result['reason']=='process_capacity_exhausted'
    assert result['candidate_processing'] is False and calls==[]


def test_known_git_failure_is_safe_and_unknown_error_is_redacted():
    def fail(message):
        def raise_error(*args):raise ValueError(message)
        return raise_error
    known=run('.',capacity_reader=info,heads=fail('Coordinator Git fetch timed_out'))
    unknown=run('.',capacity_reader=info,heads=fail('secret private data'))
    assert known['status']=='blocked' and known['reason']=='Coordinator Git fetch timed_out'
    assert unknown['reason']=='git_preflight_unavailable' and 'secret' not in str(unknown)


def test_unreadable_capacity_fails_closed_without_git():
    calls=[]
    def fail():raise OSError('private path')
    result=run('.',capacity_reader=fail,heads=lambda *a:calls.append(1))
    assert result=={'status':'blocked','reason':'process_capacity_unavailable','candidate_processing':False}
    assert calls==[]
