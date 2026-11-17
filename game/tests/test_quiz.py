"""Quiz persistence, server scoring, replay handling, and real HTTP authorization."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_auth import secure, PID
from engine import quiz
from engine.store import Store


def solve(store, player, attempt, wrong=False):
    bank = {q['id']: q for q in store.load(player)['quiz']['active']['questions']}
    for q in attempt['questions']:
        choice = bank[q['id']]['answer']
        if wrong:
            choice = (choice + 1) % len(q['options'])
        result = quiz.answer(store, player, attempt['id'], q['id'], choice, 3)
    return result


def test_sampling_hidden_answers_and_restart(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    assert len({q['id'] for q in a['questions']}) == 10
    assert all(len(q['options']) == 4 for q in a['questions'])
    actual = store.load(PID)['quiz']['active']['questions']
    assert sum(q['red_flag'] is None for q in actual) == 2
    assert all(set(q) == {'id', 'prompt', 'options'} for q in a['questions'])
    assert quiz.start(Store(tmp_path), PID)['active']['id'] == a['id']
    q = a['questions'][0]
    quiz.answer(store, PID, a['id'], q['id'], 0, 2)
    restored = quiz.state(Store(tmp_path), PID)['active']
    assert len(restored['answers']) == 1
    assert restored['answers'][0]['choice'] == 0


def test_scoring_history_and_duplicate_submission(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    result = solve(store, PID, a)
    assert result['active']['score'] == result['best_score'] == 10
    assert result['completed_count'] == len(result['history']) == 1
    last = result['active']['answers'][-1]
    retry = quiz.answer(store, PID, a['id'], last['question_id'], last['choice'], 3)
    assert retry == result
    second = quiz.start(store, PID)['active']
    assert second['id'] != a['id']
    result = solve(store, PID, second, wrong=True)
    assert result['active']['score'] == 0
    assert result['best_score'] == 10 and result['completed_count'] == 2
    assert Store(tmp_path).load(PID)['quiz']['completed_count'] == 2


@pytest.mark.parametrize('choice,confidence', [(True, 1), ('0', 1), (-1, 1), (4, 1), (0, True), (0, 0), (0, 4), (None, 1)])
def test_invalid_inputs_do_not_change_progress(tmp_path, choice, confidence):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    with pytest.raises(ValueError):
        quiz.answer(store, PID, a['id'], a['questions'][0]['id'], choice, confidence)
    assert quiz.state(store, PID)['active']['answers'] == []


def test_order_attempt_and_answer_tampering(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    for aid, qid in [('wrong', a['questions'][0]['id']), (a['id'], a['questions'][1]['id']), (a['id'], 'unknown')]:
        with pytest.raises(ValueError):
            quiz.answer(store, PID, aid, qid, 0, 1)
    quiz.answer(store, PID, a['id'], a['questions'][0]['id'], 0, 1)
    with pytest.raises(ValueError):
        quiz.answer(store, PID, a['id'], a['questions'][0]['id'], 1, 1)


def test_parallel_retry_is_counted_once(tmp_path):
    store = Store(tmp_path)
    a = quiz.start(store, PID)['active']
    args = (store, PID, a['id'], a['questions'][0]['id'], 0, 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: quiz.answer(*args), range(4)))
    assert len(quiz.state(store, PID)['active']['answers']) == 1


def test_bounded_history_and_delete(tmp_path):
    store = Store(tmp_path)
    for _ in range(22):
        result = solve(store, PID, quiz.start(store, PID)['active'])
    assert len(result['history']) == 20 and result['completed_count'] == 22
    store.delete(PID)
    assert quiz.state(store, PID)['completed_count'] == 0


def test_http_auth_isolation_and_server_score(secure):
    for path in ('state', 'start', 'answer'):
        assert secure('/api/quiz/' + path, {'player': PID})[0] == 401
    token = secure('/api/consent', {'player': PID, 'version': 'v2'})[1]['token']
    for path in ('state', 'start', 'answer'):
        assert secure('/api/quiz/' + path, {'player': PID}, token='wrong')[0] == 401
    status, data = secure('/api/quiz/start', {'player': PID}, token=token)
    assert status == 200
    a = data['active']
    answers = secure.game.store.load(PID)['quiz']['active']['questions']
    for q in answers:
        status, data = secure('/api/quiz/answer', {'player': PID, 'attempt_id': a['id'],
            'question_id': q['id'], 'choice': (q['answer'] + 1) % 4, 'confidence': 3, 'score': 999}, token=token)
        assert status == 200
    assert data['active']['score'] == 0
    assert secure('/api/quiz/state', {'player': 'other-player'}, token=token)[0] == 401
    assert secure('/api/profile?player=' + PID, method='DELETE', token=token)[0] == 200
    assert secure('/api/quiz/state', {'player': PID}, token=token)[0] == 401
