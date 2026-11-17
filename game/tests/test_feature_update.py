"""Isolated migration / 10-question / 19-achievement tests that need no persona assets."""
from engine import quiz, achievements
from engine.store import Store


def test_new_bank_and_ten_abcd(tmp_path):
    assert len(quiz.QUESTIONS) >= 20
    assert all(len(x['options']) == 4 and 0 <= x['answer'] < 4 for x in quiz.QUESTIONS)
    store = Store(tmp_path)
    a = quiz.start(store, 'tester')['active']
    assert len(a['questions']) == 10
    assert all(set(x) == {'id', 'prompt', 'options'} for x in a['questions'])
    private = store.load('tester')['quiz']['active']['questions']
    assert sum(x['red_flag'] is None for x in private) == 2
    assert sum(x['red_flag'] is not None for x in private) == 8
    assert quiz.state(store, 'tester')['active']['id'] == a['id']


def test_completed_ten_awards_and_idempotent(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, 'player')['active']
    questions = store.load('player')['quiz']['active']['questions']
    result = None
    for q in questions:
        result = quiz.answer(store, 'player', a['id'], q['id'], q['answer'], 2)
    assert result['active']['score'] == 10
    assert result['best_score_10'] == 10
    assert result['completed_count'] == 1
    assert result['history'][-1]['red_correct'] == 8
    assert result['history'][-1]['normal_correct'] == 2
    repeat = quiz.answer(store, 'player', a['id'], q['id'], q['answer'], 2)
    assert repeat['completed_count'] == 1
    awarded = {b['id'] for b in achievements.state(store, 'player')['badges'] if b['unlocked']}
    assert {'quiz_complete', 'quiz_seven', 'quiz_nine', 'quiz_red', 'quiz_normal', 'quiz_perfect'} <= awarded
    assert len(achievements.state(store, 'player')['badges']) == 19


def test_old_attempt_is_preserved_without_overwriting_history(tmp_path):
    store = Store(tmp_path)
    p = store.load('p')
    old = {'id': 'old', 'questions': [{'id': 'a', 'prompt': 'old', 'options': ['a', 'b', 'c']}],
           'answers': [], 'completed': False, 'started_at': 1}
    p['quiz'] = {'active': old, 'history': [{'id': 'past', 'total': 6, 'score': 5}],
                 'completed_count': 1, 'best_score': 5}
    store.save(p)
    state = quiz.state(store, 'p')
    assert state['active'] is None and state['needs_restart']
    new = quiz.start(store, 'p')
    assert len(new['active']['questions']) == 10
    saved = store.load('p')['quiz']
    assert saved['previous_incomplete'] == old
    assert saved['history'][0]['total'] == 6
    assert saved['completed_count'] == 1


def test_review_progress_is_deduplicated():
    e = dict(eligible=True,flags_total=3,flags_caught=2,false_positives=0,wallet=False,comeback=False)
    p = {'reviews': [{'session_at': 100, 'persona_id': 'scammer', 'achievement_stats': e, 'awake_score': 85},
                     {'session_at': 100, 'persona_id': 'scammer', 'achievement_stats': e, 'awake_score': 85}],
         'sessions': {}}
    badges = {b['id']: b for b in achievements.sync(p)['badges']}
    assert badges['review_three']['progress'] == 1
    assert badges['flag_ten']['progress'] == 2
    assert badges['high_awake']['unlocked']
