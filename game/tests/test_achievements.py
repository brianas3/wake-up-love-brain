"""Milestones use server evidence and survive resets without leaking player data."""
import copy
import pytest
from test_auth import secure, PID
from test_game import game
from engine import achievements, quiz
from engine.store import Store


def ids(result):
    return {b['id'] for b in result['badges'] if b['unlocked']}


def evidence(**kwargs):
    return dict(eligible=True, flags_total=3, flags_caught=3, false_positives=0, wallet=False, comeback=False, **kwargs)


def profile_with(e, pid='avoidant'):
    return {'sessions': {}, 'reviews': [{'persona_id': pid, 'achievement_stats': e}]}


def test_catalog_is_empty():
    result = achievements.sync({})
    assert len(result['badges']) == 19 and not ids(result)
    assert all(b['progress'] == 0 and b['unlocked_at'] is None for b in result['badges'])


@pytest.mark.parametrize('total,caught,false,expected', [(0, 0, 0, set()), (3, 0, 0, set()),
    (3, 2, 0, {'precise'}), (3, 3, 0, {'precise', 'all_flags'}), (3, 3, 1, set()), (201, 200, 0, {'precise'})])
def test_exact_counts_not_rounded_percentages(total, caught, false, expected):
    e = evidence(); e.update(flags_total=total, flags_caught=caught, false_positives=false)
    result = ids(achievements.sync(profile_with(e)))
    assert result & {'precise', 'all_flags'} == expected


def test_ineligible_and_unknown_personas():
    e = evidence(); e['eligible'] = False
    assert not ids(achievements.sync(profile_with(e)))
    p = profile_with(evidence(), 'invented')
    b = next(b for b in achievements.sync(p)['badges'] if b['id'] == 'all_personas')
    assert b['progress'] == 0


def test_persona_progress_and_durable_unlock():
    p = {'reviews': [], 'sessions': {}}
    for n, pid in enumerate(sorted(achievements.PERSONAS), 1):
        p['reviews'].append({'persona_id': pid, 'achievement_stats': evidence()})
        b = next(b for b in achievements.sync(p)['badges'] if b['id'] == 'all_personas')
        assert b['progress'] == n and b['unlocked'] == (n == 5)
    stamp = copy.deepcopy(p['achievements'])
    assert achievements.sync(p)['newly_unlocked'] == []
    assert p['achievements'] == stamp
    p['reviews'] = []
    assert 'all_personas' in ids(achievements.sync(p))


def test_money_requires_request_natural_end_and_no_transfer():
    state = {'messages': [{'role': 'npc', 'red_flags': ['urgent_money']}, {'role': 'player', 'kind': 'awake'}], 'money_events': []}
    scores = {'flags_total': 1, 'flags_caught': 1, 'false_positives': 0}
    e = achievements.review_evidence(state, scores, True)
    assert 'wallet' in ids(achievements.sync(profile_with(e, 'scammer')))
    assert 'wallet' not in ids(achievements.sync(profile_with(e, 'avoidant')))
    assert not achievements.review_evidence(state, scores, False)['wallet']
    state['money_events'] = [{'amount': 0}]
    assert not achievements.review_evidence(state, scores, True)['wallet']
    state['money_events'] = []; state['messages'][0]['red_flags'] = []
    assert not achievements.review_evidence(state, scores, True)['wallet']


@pytest.mark.parametrize('kinds,expected', [(['brain', 'awake'], True), (['brain', 'neutral', 'neutral', 'awake'], True),
    (['brain', 'neutral', 'neutral', 'neutral', 'awake'], False), (['awake', 'brain'], False)])
def test_comeback_window(kinds, expected):
    state = {'messages': [{'role': 'player', 'kind': k} for k in kinds]}
    e = achievements.review_evidence(state, {'flags_total': 0, 'flags_caught': 0, 'false_positives': 0}, False)
    assert e['comeback'] is expected


def test_review_hook_no_zero_turn_award_and_reset_preserves(game):
    game.start('p1', 'avoidant')
    assert not ids(game.review('p1', 'avoidant', finish=True)['achievements'])
    game.reset('p1', 'avoidant'); game.start('p1', 'avoidant')
    game.send('p1', 'avoidant', text='我想先了解你的想法')
    result = game.review('p1', 'avoidant', finish=True)['achievements']
    assert 'first_review' in ids(result)
    first_stamp = game.store.load('p1')['achievements']['first_review']
    assert not game.review('p1', 'avoidant')['achievements']['newly_unlocked']
    game.reset('p1', 'avoidant')
    assert 'first_review' in ids(achievements.state(game.store, 'p1'))
    assert game.store.load('p1')['achievements']['first_review'] == first_stamp


def test_legacy_review_backfill_without_guessing(game):
    game.start('p1', 'avoidant'); game.send('p1', 'avoidant', text='我需要自己的時間')
    game.review('p1', 'avoidant', finish=True)
    p = game.store.load('p1'); p.pop('achievements')
    for r in p['reviews']: r.pop('achievement_stats')
    game.store.save(p)
    assert 'first_review' in ids(achievements.state(game.store, 'p1'))
    p.pop('achievements', None); p['sessions'] = {}; game.store.save(p)
    assert not ids(achievements.state(game.store, 'p1'))


def test_quiz_hook_persistence_and_delete(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    actual = store.load(PID)['quiz']['active']['questions']
    for q in actual:
        quiz.answer(store, PID, a['id'], q['id'], q['answer'], 2)
    saved = Store(tmp_path).load(PID)
    assert {'quiz_complete', 'quiz_perfect'} <= saved['achievements'].keys()
    assert {'quiz_complete', 'quiz_perfect', 'quiz_seven', 'quiz_nine', 'quiz_red', 'quiz_normal'} <= ids(achievements.state(Store(tmp_path), PID))
    quiz.start(store, PID)
    assert 'quiz_perfect' in ids(achievements.state(store, PID))
    store.delete(PID)
    assert not ids(achievements.state(store, PID))


def test_http_auth_catalog_tampering_and_privacy(secure):
    assert secure('/api/achievements/catalog')[0] == 200
    assert secure('/api/achievements', {'player': PID})[0] == 401
    token = secure('/api/consent', {'player': PID, 'version': 'v2'})[1]['token']
    assert secure('/api/achievements', {'player': PID}, token='wrong')[0] == 401
    status, result = secure('/api/achievements', {'player': PID, 'achievements': {'wallet': 1}, 'unlocked': True}, token=token)
    assert status == 200 and not ids(result)
    assert set(result) == {'badges', 'unlocked_count', 'total', 'newly_unlocked'}
    assert secure('/api/achievements', {'player': 'other-player'}, token=token)[0] == 401
    assert secure('/api/achievements/catalog')[1]['unlocked_count'] == 0
