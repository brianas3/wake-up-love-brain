"""Persistent, server-verified achievements. Never trust the client's claimed progress."""
from __future__ import annotations
import time
from . import scoring

PERSONAS = {'avoidant', 'dependent', 'anxious', 'scammer', 'player'}
MONEY_FLAGS = {'urgent_money', 'small_invest', 'pressure_loan', 'withdraw_fee', 'insider_tip'}

# id, title, description, icon, group, target, rarity
BADGES = (
    ('first_review', '第一步，看見自己', '實際回覆至少一次，完成一局互動覆盤。', 'note', '互動練習', 1, '一般'),
    ('precise', '有憑有據', '單局至少抓到一則紅旗，沒有誤標正常訊息。', 'check', '互動練習', 1, '一般'),
    ('all_flags', '紅旗不漏接', '單局抓出所有紅旗，且沒有誤標。', 'flag', '互動練習', 1, '稀有'),
    ('review_three', '持續練習', '累積完成 3 局有實際回覆的覆盤。', 'note', '互動練習', 3, '一般'),
    ('review_five', '愈練愈清醒', '累積完成 5 局有實際回覆的覆盤。', 'medal', '互動練習', 5, '進階'),
    ('three_personas', '觀察不同關係', '與 3 種不同角色互動並完成覆盤。', 'users', '互動練習', 3, '進階'),
    ('all_personas', '五種視角', '與 5 種角色各完成一次實際互動及覆盤。', 'users', '互動練習', 5, '傳說'),
    ('flag_ten', '紅旗偵探', '累積在已覆盤的局數中正確抓到 10 則紅旗。', 'flag', '互動練習', 10, '進階'),
    ('high_awake', '清醒滿點', '一局有實際回覆的覆盤，清醒分數至少 80 分。', 'brain', '互動練習', 1, '稀有'),
    ('wallet', '守住荷包', '愛情騙子局遇到金錢誘導、自然走完劇情且沒有轉款，再完成覆盤。', 'medal', '互動練習', 1, '稀有'),
    ('comeback', '重新選擇', '一局中曾順從對方，三次回覆內轉為清醒選擇，再完成覆盤。', 'thumb', '互動練習', 1, '稀有'),
    ('quiz_complete', '現實檢核', '完成一次情境小測驗。', 'note', '情境測驗', 1, '一般'),
    ('quiz_three', '練習不間斷', '累積完成 3 次情境小測驗。', 'star', '情境測驗', 3, '一般'),
    ('quiz_five', '判斷練習家', '累積完成 5 次情境小測驗。', 'medal', '情境測驗', 5, '進階'),
    ('quiz_seven', '七成警覺', '任一次新版 10 題測驗答對至少 7 題。', 'brain', '情境測驗', 1, '一般'),
    ('quiz_nine', '眼光銳利', '任一次新版 10 題測驗答對至少 9 題。', 'star-fill', '情境測驗', 1, '稀有'),
    ('quiz_red', '紅旗雷達', '同一次新版測驗中 8 道紅旗情境全部答對。', 'flag', '情境測驗', 1, '稀有'),
    ('quiz_normal', '不草木皆兵', '同一次新版測驗中 2 道正常互動題全部答對。', 'check', '情境測驗', 1, '進階'),
    ('quiz_perfect', '判斷有一套', '新版 10 題小測驗全對；舊版已獲得的滿分徽章會保留。', 'star-fill', '情境測驗', 1, '傳說'),
)


def review_evidence(state, scores, natural_end):
    players = [m for m in state.get('messages', []) if m.get('role') == 'player']
    kinds = [m.get('kind') for m in players]
    return {
        'eligible': bool(players) and not bool(state.get('safety')),
        'flags_total': scores['flags_total'], 'flags_caught': scores['flags_caught'],
        'false_positives': scores['false_positives'],
        'wallet': bool(natural_end) and not state.get('money_events') and any(
            MONEY_FLAGS.intersection(m.get('red_flags', [])) for m in state.get('messages', []) if m.get('role') == 'npc'),
        'comeback': any(kind == 'brain' and 'awake' in kinds[i + 1:i + 4] for i, kind in enumerate(kinds)),
    }


def sync(profile):
    """Update unlocked timestamps and return progress; caller owns the player's lock."""
    reviews = profile.get('reviews', [])
    evidence = []
    seen_sessions = set()
    for i, r in enumerate(reviews):
        identity = r.get('session_at')
        if identity is not None:
            if identity in seen_sessions:
                continue
            seen_sessions.add(identity)
        evidence.append((r.get('persona_id'), r.get('achievement_stats', {}), r.get('awake_score', 0)))
    # Recover only existing reviewed sessions when an old summary lacks stats;
    # avoid counting the same session twice when its summary exists.
    for pid, st in profile.get('sessions', {}).items():
        if not st.get('reviewed') or st.get('created_at') in seen_sessions:
            continue
        seen_sessions.add(st.get('created_at'))
        score = scoring.compute(st)
        evidence.append((pid, review_evidence(st, score, bool(
            st.get('stage') == 5 and st.get('stage5_turns', 0) >= 2 and st.get('ended'))),
            score.get('awake_score', 0)))
    valid = [(pid, e, score) for pid, e, score in evidence if e.get('eligible')]
    personas = {pid for pid, _, _ in valid} & PERSONAS
    quiz = profile.get('quiz', {})
    history10 = [h for h in quiz.get('history', []) if h.get('total') == 10]
    best10 = max(quiz.get('best_score_10', 0),
                 max((h.get('score', 0) for h in history10), default=0))
    progress = {
        'first_review': int(bool(valid)),
        'precise': int(any(e.get('flags_caught', 0) > 0 and e.get('false_positives') == 0 for _, e, _ in valid)),
        'all_flags': int(any(e.get('flags_total', 0) > 0 and e.get('flags_caught') == e['flags_total']
                             and e.get('false_positives') == 0 for _, e, _ in valid)),
        'review_three': len(valid),
        'review_five': len(valid),
        'three_personas': len(personas),
        'all_personas': len(personas),
        'flag_ten': sum(max(0, e.get('flags_caught', 0)) for _, e, _ in valid),
        'high_awake': int(any(score >= 80 for _, _, score in valid)),
        'wallet': int(any(pid == 'scammer' and e.get('wallet') for pid, e, _ in valid)),
        'comeback': int(any(e.get('comeback') for _, e, _ in valid)),
        'quiz_complete': int(quiz.get('completed_count', 0) > 0),
        'quiz_three': quiz.get('completed_count', 0),
        'quiz_five': quiz.get('completed_count', 0),
        'quiz_seven': int(best10 >= 7),
        'quiz_nine': int(best10 >= 9),
        'quiz_red': int(any(h.get('red_correct', 0) == 8 for h in history10)),
        'quiz_normal': int(any(h.get('normal_correct', 0) == 2 for h in history10)),
        'quiz_perfect': int(best10 >= 10),
    }
    unlocked = profile.setdefault('achievements', {})
    now = time.time()
    newly = []
    for key, title, description, icon, group, target, rarity in BADGES:
        if progress[key] >= target and key not in unlocked:
            unlocked[key] = now
            newly.append(key)
    badges = [
        {'id': key, 'title': title, 'description': description, 'icon': icon,
         'group': group, 'rarity': rarity, 'target': target,
         'progress': target if key in unlocked else min(progress[key], target),
         'unlocked': key in unlocked, 'unlocked_at': unlocked.get(key)}
        for key, title, description, icon, group, target, rarity in BADGES
    ]
    return {'badges': badges, 'unlocked_count': sum(b['unlocked'] for b in badges),
            'total': len(badges), 'newly_unlocked': newly}


def state(store, player):
    with store.lock(player):
        profile = store.load(player)
        before = dict(profile.get('achievements', {}))
        result = sync(profile)
        if profile['achievements'] != before:
            store.save(profile)
        return result
