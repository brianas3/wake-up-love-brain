"""Server-scored ten-question ABCD practice, compatible with existing player saves.

Answers and explanations remain server-owned until a particular item is submitted.
The original 6-question data file is never modified by this feature.
"""
from __future__ import annotations
import copy
import json
import secrets
import time
from pathlib import Path
from . import achievements

QUESTIONS = json.loads((Path(__file__).resolve().parent.parent / 'data/quiz_v2.json').read_text(encoding='utf-8'))
HISTORY_LIMIT = 20
QUESTION_COUNT = 10
QUIZ_VERSION = 2


def _fresh():
    return {'active': None, 'history': [], 'completed_count': 0, 'best_score': 0, 'best_score_10': 0}


def _data(profile):
    data = profile.setdefault('quiz', _fresh())
    data.setdefault('history', [])
    data.setdefault('completed_count', 0)
    data.setdefault('best_score', 0)
    data.setdefault('best_score_10', max((h.get('score', 0) for h in data['history']
                                          if h.get('total') == QUESTION_COUNT), default=0))
    return data


def _legacy_incomplete(attempt):
    return bool(attempt and not attempt.get('completed') and (
        len(attempt.get('questions', [])) != QUESTION_COUNT or
        any(len(q.get('options', [])) != 4 for q in attempt.get('questions', []))))


def _view(data):
    out = copy.deepcopy(data)
    attempt = out.get('active')
    out['needs_restart'] = _legacy_incomplete(attempt)
    if out['needs_restart']:
        # Old unfinished 6-question attempts are saved on start, not silently deleted.
        out['active'] = None
    elif attempt:
        attempt['questions'] = [{k: q[k] for k in ('id', 'prompt', 'options')} for q in attempt['questions']]
    out.pop('previous_incomplete', None)
    return out


def state(store, player):
    with store.lock(player):
        return _view(store.load(player).get('quiz', _fresh()))


def start(store, player):
    with store.lock(player):
        profile = store.load(player)
        data = _data(profile)
        old = data.get('active')
        if old and not old.get('completed') and not _legacy_incomplete(old):
            return _view(data)
        if _legacy_incomplete(old):
            # Keep an old incomplete run as a backup inside the existing player save.
            data['previous_incomplete'] = old
        rng = secrets.SystemRandom()
        flagged = rng.sample([q for q in QUESTIONS if q['red_flag']], 8)
        normal = rng.sample([q for q in QUESTIONS if not q['red_flag']], 2)
        selected = flagged + normal
        rng.shuffle(selected)
        data['active'] = {'id': secrets.token_urlsafe(18), 'version': QUIZ_VERSION,
                          'questions': copy.deepcopy(selected), 'answers': [],
                          'completed': False, 'started_at': time.time()}
        store.save(profile)
        return _view(data)


def answer(store, player, attempt_id, question_id, choice, confidence):
    if not isinstance(attempt_id, str) or not isinstance(question_id, str):
        raise ValueError('attempt_id and question_id must be strings')
    if type(choice) is not int or type(confidence) is not int or confidence not in (1, 2, 3):
        raise ValueError('choice and confidence must be integers; confidence must be 1, 2 or 3')
    with store.lock(player):
        profile = store.load(player)
        data = _data(profile)
        attempt = data.get('active')
        if not attempt or attempt['id'] != attempt_id or _legacy_incomplete(attempt):
            raise ValueError('測驗已更新，請關閉並重新開啟小測驗。')
        for saved in attempt['answers']:
            if saved['question_id'] == question_id:
                if saved['choice'] == choice and saved['confidence'] == confidence:
                    return _view(data)
                raise ValueError('這題已確認答案，不能更改。')
        if attempt['completed']:
            raise ValueError('這份測驗已完成。')
        q = attempt['questions'][len(attempt['answers'])]
        if q['id'] != question_id or not 0 <= choice < len(q['options']):
            raise ValueError('題目或選項無效，請重新開啟小測驗。')
        attempt['answers'].append({'question_id': q['id'], 'choice': choice,
                                   'confidence': confidence, 'correct': choice == q['answer'],
                                   'correct_choice': q['answer'], 'explanation': q['explanation'],
                                   'red_flag': q['red_flag']})
        if len(attempt['answers']) == len(attempt['questions']):
            attempt['completed'] = True
            attempt['score'] = sum(a['correct'] for a in attempt['answers'])
            attempt['completed_at'] = time.time()
            data['completed_count'] += 1
            data['best_score'] = max(data['best_score'], attempt['score'])
            if len(attempt['questions']) == QUESTION_COUNT:
                data['best_score_10'] = max(data['best_score_10'], attempt['score'])
            red_correct = sum(a['correct'] and a['red_flag'] is not None for a in attempt['answers'])
            normal_correct = sum(a['correct'] and a['red_flag'] is None for a in attempt['answers'])
            streak = best_streak = 0
            for a in attempt['answers']:
                streak = streak + 1 if a['correct'] else 0
                best_streak = max(best_streak, streak)
            data['history'].append({'id': attempt['id'], 'score': attempt['score'],
                                    'total': len(attempt['questions']),
                                    'completed_at': attempt['completed_at'],
                                    'red_correct': red_correct, 'normal_correct': normal_correct,
                                    'longest_streak': best_streak})
            data['history'] = data['history'][-HISTORY_LIMIT:]
            earned = achievements.sync(profile)
        else:
            earned = None
        store.save(profile)
        result = _view(data)
        if earned:
            result['new_badges'] = [b['title'] for b in earned['badges']
                                    if b['id'] in earned['newly_unlocked']]
        return result
