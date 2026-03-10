import json
import math
import os
import random
from itertools import combinations
from tempfile import NamedTemporaryFile
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

st.set_page_config(page_title='台球比赛积分管理（加速版）', layout='wide')

APP_TITLE = '🎱 台球比赛积分管理（加速版）'
DATA_FILE = 'billiards_tournament_data.json'
WIN_POINTS = 2
LOSS_POINTS = 0
QUALIFY_SLOTS = 2
FIRST_SLOTS = 1
RESULT_OPTIONS = ['未录入', '2:0', '2:1', '1:2', '0:2']

# 这里可以直接改名单
GROUPS = {
    'A组': ['白云峰', '程云喜', '赵国强', '刘士伟'],
    'B组': ['张太忠', '孙孝沅', '齐宝奎', '耿旭'],
    'C组': ['耿桢', '程谟臣', '李健', '赵磊'],
    'D组': ['尹家林', '刘祥', '赵洪伟', '王绪东'],
    'E组': ['邹贤盛', '毕庶安', '陈凤瑞', '付延菁'],
}

MATCHES = {group: list(combinations(players, 2)) for group, players in GROUPS.items()}


# =========================
# 认证：仅指定用户可改比分
# =========================
# 推荐做法：在 Streamlit Cloud 的 Secrets 里配置，不要把密码直接写进 GitHub。
# 支持两种方式：
# 1) [editor_users]
#    裁判1 = "abc123"
#    裁判2 = "def456"
# 2) EDITOR_USERS_JSON = '{"裁判1":"abc123","裁判2":"def456"}'


def load_editor_users() -> Dict[str, str]:
    users: Dict[str, str] = {}

    try:
        if 'editor_users' in st.secrets:
            sec = st.secrets['editor_users']
            try:
                users = {str(k): str(v) for k, v in sec.items()}
            except Exception:
                users = {}
    except Exception:
        users = {}

    if not users:
        try:
            raw = st.secrets.get('EDITOR_USERS_JSON', '')
            if raw:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    users = {str(k): str(v) for k, v in obj.items()}
        except Exception:
            users = {}

    if not users:
        raw = os.environ.get('EDITOR_USERS_JSON', '')
        if raw:
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    users = {str(k): str(v) for k, v in obj.items()}
            except Exception:
                users = {}

    return users


EDITOR_USERS = load_editor_users()


# =========================
# 基础数据读写
# =========================

def default_strengths() -> Dict[str, float]:
    return {player: 1.0 for players in GROUPS.values() for player in players}


def default_data() -> Dict:
    return {
        'results': {},
        'strengths': default_strengths(),
        'draw_positions': [],
    }


def atomic_write_json(path: str, data: Dict) -> None:
    folder = os.path.dirname(path) or '.'
    with NamedTemporaryFile('w', delete=False, dir=folder, encoding='utf-8') as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        temp_name = tmp.name
    os.replace(temp_name, path)


def load_data() -> Dict:
    data = default_data()
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update({k: v for k, v in loaded.items() if k in data})
        except Exception:
            pass

    data.setdefault('results', {})
    data.setdefault('strengths', {})
    data.setdefault('draw_positions', [])

    for player, value in default_strengths().items():
        data['strengths'].setdefault(player, value)

    return data


def save_data(data: Dict) -> None:
    atomic_write_json(DATA_FILE, data)
    clear_cached_views()


# =========================
# 工具函数
# =========================

def clear_cached_views() -> None:
    compute_group_table_cached.clear()
    compute_group_probabilities_cached.clear()
    compute_group_matrix_cached.clear()



def match_key(group: str, a: str, b: str) -> str:
    x, y = sorted([a, b])
    return f'{group}|{x}|{y}'



def parse_result_text(text: str):
    if text == '未录入':
        return None
    a, b = text.split(':')
    return int(a), int(b)



def result_text(score_a: int, score_b: int) -> str:
    return f'{score_a}:{score_b}'



def validate_best_of_three(score_a: int, score_b: int) -> bool:
    return (score_a, score_b) in {(2, 0), (2, 1), (1, 2), (0, 2)}



def build_group_result_signature(group: str, all_results: Dict) -> Tuple[Tuple[str, str, int, int], ...]:
    rows = []
    for a, b in MATCHES[group]:
        key = match_key(group, a, b)
        if key in all_results:
            rows.append((a, b, int(all_results[key]['a']), int(all_results[key]['b'])))
    return tuple(rows)



def build_strength_signature() -> Tuple[Tuple[str, float], ...]:
    strengths = st.session_state['data']['strengths']
    return tuple(sorted((player, round(float(strengths.get(player, 1.0)), 6)) for player in default_strengths()))



def result_map_from_signature(group_sig: Tuple[Tuple[str, str, int, int], ...]) -> Dict[Tuple[str, str], Tuple[int, int]]:
    return {(a, b): (sa, sb) for a, b, sa, sb in group_sig}



def get_score_from_group_map(group_map: Dict[Tuple[str, str], Tuple[int, int]], a: str, b: str):
    if (a, b) in group_map:
        return group_map[(a, b)]
    if (b, a) in group_map:
        sb, sa = group_map[(b, a)]
        return sa, sb
    return None



def init_stats(players: List[str]) -> Dict[str, Dict]:
    return {
        p: {
            '选手': p,
            '场次': 0,
            '胜场': 0,
            '负场': 0,
            '积分': 0,
            '胜局': 0,
            '负局': 0,
            '净胜局': 0,
        }
        for p in players
    }



def apply_match(stats: Dict[str, Dict], a: str, b: str, score_a: int, score_b: int) -> None:
    if not validate_best_of_three(score_a, score_b):
        raise ValueError(f'非法比分：{a} vs {b} = {score_a}:{score_b}')

    stats[a]['场次'] += 1
    stats[b]['场次'] += 1

    stats[a]['胜局'] += score_a
    stats[a]['负局'] += score_b
    stats[b]['胜局'] += score_b
    stats[b]['负局'] += score_a

    if score_a > score_b:
        stats[a]['胜场'] += 1
        stats[b]['负场'] += 1
        stats[a]['积分'] += WIN_POINTS
        stats[b]['积分'] += LOSS_POINTS
    else:
        stats[b]['胜场'] += 1
        stats[a]['负场'] += 1
        stats[b]['积分'] += WIN_POINTS
        stats[a]['积分'] += LOSS_POINTS

    stats[a]['净胜局'] = stats[a]['胜局'] - stats[a]['负局']
    stats[b]['净胜局'] = stats[b]['胜局'] - stats[b]['负局']



def compute_stats_from_map(players: List[str], group_map: Dict[Tuple[str, str], Tuple[int, int]]) -> Dict[str, Dict]:
    stats = init_stats(players)
    for (a, b), (score_a, score_b) in group_map.items():
        apply_match(stats, a, b, score_a, score_b)
    return stats



def compute_mini_stats_from_map(group_map: Dict[Tuple[str, str], Tuple[int, int]], subset_players: List[str]) -> Dict[str, Dict]:
    subset = set(subset_players)
    stats = init_stats(subset_players)
    for (a, b), (score_a, score_b) in group_map.items():
        if a in subset and b in subset:
            apply_match(stats, a, b, score_a, score_b)
    return stats



def player_full_sort_key(player: str, stats: Dict[str, Dict]) -> Tuple:
    return (
        -stats[player]['积分'],
        -stats[player]['净胜局'],
        -stats[player]['胜局'],
        player,
    )



def sorted_players_by_rules(players: List[str], group_map: Dict[Tuple[str, str], Tuple[int, int]]) -> List[str]:
    stats = compute_stats_from_map(players, group_map)

    point_buckets: Dict[int, List[str]] = {}
    for p in players:
        point_buckets.setdefault(stats[p]['积分'], []).append(p)

    ordered: List[str] = []
    for pts in sorted(point_buckets.keys(), reverse=True):
        bucket = point_buckets[pts]
        if len(bucket) == 1:
            ordered.extend(bucket)
            continue

        mini_stats = compute_mini_stats_from_map(group_map, bucket)
        mini_buckets: Dict[Tuple[int, int, int], List[str]] = {}
        for p in bucket:
            k = (
                mini_stats[p]['积分'],
                mini_stats[p]['净胜局'],
                mini_stats[p]['胜局'],
            )
            mini_buckets.setdefault(k, []).append(p)

        for k in sorted(mini_buckets.keys(), reverse=True):
            sub = mini_buckets[k]
            if len(sub) == 1:
                ordered.extend(sub)
            else:
                ordered.extend(sorted(sub, key=lambda x: player_full_sort_key(x, stats)))

    return ordered



def tie_bucket_by_all_rules(players: List[str], group_map: Dict[Tuple[str, str], Tuple[int, int]]) -> List[List[str]]:
    stats = compute_stats_from_map(players, group_map)

    point_buckets: Dict[int, List[str]] = {}
    for p in players:
        point_buckets.setdefault(stats[p]['积分'], []).append(p)

    final_groups: List[List[str]] = []
    for pts in sorted(point_buckets.keys(), reverse=True):
        bucket = point_buckets[pts]
        if len(bucket) == 1:
            final_groups.append(bucket)
            continue

        mini_stats = compute_mini_stats_from_map(group_map, bucket)
        mini_buckets: Dict[Tuple[int, int, int], List[str]] = {}
        for p in bucket:
            k = (
                mini_stats[p]['积分'],
                mini_stats[p]['净胜局'],
                mini_stats[p]['胜局'],
            )
            mini_buckets.setdefault(k, []).append(p)

        for mini_key in sorted(mini_buckets.keys(), reverse=True):
            sub = mini_buckets[mini_key]
            if len(sub) == 1:
                final_groups.append(sub)
                continue

            overall_buckets: Dict[Tuple[int, int], List[str]] = {}
            for p in sub:
                kk = (stats[p]['净胜局'], stats[p]['胜局'])
                overall_buckets.setdefault(kk, []).append(p)

            for kk in sorted(overall_buckets.keys(), reverse=True):
                same = overall_buckets[kk]
                final_groups.append(sorted(same))

    return final_groups



def rank_group_rows(group: str, group_map: Dict[Tuple[str, str], Tuple[int, int]]) -> Tuple[pd.DataFrame, List[str], Dict[str, Dict]]:
    players = GROUPS[group]
    stats = compute_stats_from_map(players, group_map)
    ordered = sorted_players_by_rules(players, group_map)

    rows = []
    for rank_idx, p in enumerate(ordered, start=1):
        row = dict(stats[p])
        row['名次'] = rank_idx
        rows.append(row)

    df = pd.DataFrame(rows)[['名次', '选手', '场次', '胜场', '负场', '积分', '胜局', '负局', '净胜局']]
    return df, ordered, stats


# =========================
# 出线率：公平处理并列跨线
# =========================

def winner_prob(strength_a: float, strength_b: float) -> float:
    total = max(strength_a, 0.0) + max(strength_b, 0.0)
    if total <= 0:
        return 0.5
    return max(strength_a, 0.0) / total



def sweep_prob(p_match_win: float) -> float:
    return min(0.80, max(0.35, 0.35 + abs(p_match_win - 0.5)))



def outcome_distribution(a: str, b: str, strengths: Dict[str, float]):
    sa = float(strengths.get(a, 1.0))
    sb = float(strengths.get(b, 1.0))
    pa = winner_prob(sa, sb)
    pb = 1.0 - pa

    pa20_cond = sweep_prob(pa)
    pb20_cond = sweep_prob(pb)

    outcomes = [
        ((2, 0), pa * pa20_cond),
        ((2, 1), pa * (1 - pa20_cond)),
        ((1, 2), pb * (1 - pb20_cond)),
        ((0, 2), pb * pb20_cond),
    ]
    total = sum(prob for _, prob in outcomes)
    if total <= 0:
        return [((2, 1), 0.5), ((1, 2), 0.5)]
    return [(score, prob / total) for score, prob in outcomes]



def fair_share_top_k(players: List[str], group_map: Dict[Tuple[str, str], Tuple[int, int]], k: int) -> Dict[str, float]:
    ordered_groups = tie_bucket_by_all_rules(players, group_map)
    remain = k
    shares = {p: 0.0 for p in players}

    for bucket in ordered_groups:
        if remain <= 0:
            break
        if len(bucket) <= remain:
            for p in bucket:
                shares[p] = 1.0
            remain -= len(bucket)
        else:
            frac = remain / len(bucket)
            for p in bucket:
                shares[p] = frac
            remain = 0
            break

    return shares



def exact_group_probabilities(group: str, all_results: Dict, strengths: Dict[str, float]):
    players = GROUPS[group]
    current_group_sig = build_group_result_signature(group, all_results)
    current_map = result_map_from_signature(current_group_sig)

    remaining = []
    for a, b in MATCHES[group]:
        if get_score_from_group_map(current_map, a, b) is None:
            remaining.append((a, b))

    qualify_prob = {p: 0.0 for p in players}
    first_prob = {p: 0.0 for p in players}

    if not remaining:
        qshare = fair_share_top_k(players, current_map, QUALIFY_SLOTS)
        fshare = fair_share_top_k(players, current_map, FIRST_SLOTS)
        return qshare, fshare

    def dfs(idx: int, group_map: Dict[Tuple[str, str], Tuple[int, int]], path_prob: float):
        if idx == len(remaining):
            qshare = fair_share_top_k(players, group_map, QUALIFY_SLOTS)
            fshare = fair_share_top_k(players, group_map, FIRST_SLOTS)
            for p in players:
                qualify_prob[p] += path_prob * qshare[p]
                first_prob[p] += path_prob * fshare[p]
            return

        a, b = remaining[idx]
        for (sa, sb), p in outcome_distribution(a, b, strengths):
            next_map = dict(group_map)
            next_map[(a, b)] = (sa, sb)
            dfs(idx + 1, next_map, path_prob * p)

    dfs(0, current_map, 1.0)

    for p in players:
        qualify_prob[p] = max(0.0, min(1.0, qualify_prob[p]))
        first_prob[p] = max(0.0, min(1.0, first_prob[p]))

    return qualify_prob, first_prob


# =========================
# 缓存视图（加速）
# =========================

@st.cache_data(show_spinner=False)
def compute_group_table_cached(group: str, group_sig: Tuple[Tuple[str, str, int, int], ...]):
    group_map = result_map_from_signature(group_sig)
    return rank_group_rows(group, group_map)


@st.cache_data(show_spinner='正在计算出线率...', ttl=5)
def compute_group_probabilities_cached(group: str, group_sig: Tuple[Tuple[str, str, int, int], ...], strength_sig):
    all_results = {}
    for a, b, sa, sb in group_sig:
        key = match_key(group, a, b)
        all_results[key] = {'a': sa, 'b': sb}
    strengths = {player: val for player, val in strength_sig}
    return exact_group_probabilities(group, all_results, strengths)


@st.cache_data(show_spinner=False)
def compute_group_matrix_cached(group: str, group_sig: Tuple[Tuple[str, str, int, int], ...]):
    players = GROUPS[group]
    group_map = result_map_from_signature(group_sig)
    matrix = pd.DataFrame('', index=players, columns=players)
    for p in players:
        matrix.loc[p, p] = '—'
    for a, b in MATCHES[group]:
        score = get_score_from_group_map(group_map, a, b)
        if score is None:
            matrix.loc[a, b] = '待赛'
            matrix.loc[b, a] = '待赛'
        else:
            sa, sb = score
            matrix.loc[a, b] = f'{sa}:{sb}'
            matrix.loc[b, a] = f'{sb}:{sa}'
    return matrix


# =========================
# 会话状态与权限
# =========================

def ensure_session_state():
    if 'data' not in st.session_state:
        st.session_state['data'] = load_data()
    if 'logged_in_user' not in st.session_state:
        st.session_state['logged_in_user'] = None
    if 'view_page' not in st.session_state:
        st.session_state['view_page'] = '首页概览'



def current_data() -> Dict:
    return st.session_state['data']



def is_editor() -> bool:
    return st.session_state.get('logged_in_user') in EDITOR_USERS



def login_panel():
    with st.sidebar:
        st.markdown('## 账号权限')
        if not EDITOR_USERS:
            st.info('当前未配置录分员账号，系统已进入只读模式。')
            return

        if is_editor():
            st.success(f"已登录录分员：{st.session_state['logged_in_user']}")
            if st.button('退出登录', use_container_width=True):
                st.session_state['logged_in_user'] = None
                st.rerun()
            return

        with st.form('login_form'):
            username = st.text_input('账号')
            password = st.text_input('密码', type='password')
            ok = st.form_submit_button('登录为录分员', use_container_width=True)
            if ok:
                if username in EDITOR_USERS and EDITOR_USERS[username] == password:
                    st.session_state['logged_in_user'] = username
                    st.success('登录成功')
                    st.rerun()
                else:
                    st.error('账号或密码错误')


# =========================
# 业务函数
# =========================

def group_signature(group: str):
    return build_group_result_signature(group, current_data()['results'])



def strength_signature():
    return tuple(sorted((player, round(float(current_data()['strengths'].get(player, 1.0)), 6)) for player in default_strengths()))



def get_group_table(group: str):
    return compute_group_table_cached(group, group_signature(group))



def get_group_probabilities(group: str):
    return compute_group_probabilities_cached(group, group_signature(group), strength_signature())



def get_group_matrix(group: str):
    return compute_group_matrix_cached(group, group_signature(group))



def all_matches_finished(all_results: Dict) -> bool:
    total = sum(len(v) for v in MATCHES.values())
    return len(all_results) == total



def qualified_players_df(all_results: Dict) -> pd.DataFrame:
    rows = []
    for group in GROUPS:
        df, ranking, _ = get_group_table(group)
        top2 = ranking[:2]
        rows.append({'小组': group, '组内名次': 1, '选手': top2[0]})
        rows.append({'小组': group, '组内名次': 2, '选手': top2[1]})
    return pd.DataFrame(rows)



def save_current_data():
    save_data(current_data())



def reset_results():
    st.session_state['data']['results'] = {}
    st.session_state['data']['draw_positions'] = []
    save_current_data()



def reset_strengths():
    st.session_state['data']['strengths'] = default_strengths()
    save_current_data()


# =========================
# 页面
# =========================
ensure_session_state()
login_panel()

data = current_data()
results = data['results']
strengths = data['strengths']

st.title(APP_TITLE)
st.caption('支持：赛果录入、实时积分榜、加速版出线率、第二阶段抽签；仅指定录分员可修改。')

with st.sidebar:
    st.markdown('## 页面导航')
    page = st.radio(
        '请选择页面',
        ['首页概览', '赛果录入', '小组积分榜', '出线率预测', '第二阶段抽签', '系统设置'],
        index=['首页概览', '赛果录入', '小组积分榜', '出线率预测', '第二阶段抽签', '系统设置'].index(st.session_state['view_page']),
    )
    st.session_state['view_page'] = page

page = st.session_state['view_page']

total_matches = sum(len(v) for v in MATCHES.values())
finished_matches = len(results)
waiting_matches = total_matches - finished_matches

if page == '首页概览':
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('总场次', total_matches)
    c2.metric('已完赛', finished_matches)
    c3.metric('待进行', waiting_matches)
    c4.metric('录分权限', '已开启' if is_editor() else '只读')

    st.markdown('## 当前各组前二')
    cols = st.columns(len(GROUPS))
    for idx, group in enumerate(GROUPS):
        df, ranking, _ = get_group_table(group)
        with cols[idx]:
            st.markdown(f'### {group}')
            st.write(f'1. {ranking[0]}')
            st.write(f'2. {ranking[1]}')

    st.markdown('## 当前暂定出线名单')
    st.dataframe(qualified_players_df(results), use_container_width=True)

elif page == '赛果录入':
    st.subheader('录入或修改比赛结果')
    if not is_editor():
        st.warning('你当前是只读模式，只能查看，不能修改比分。')

    chosen_group = st.selectbox('选择小组', list(GROUPS.keys()))
    st.markdown(f'### {chosen_group} 当前对阵矩阵')
    st.dataframe(get_group_matrix(chosen_group), use_container_width=True)

    if is_editor():
        with st.form(f'form_{chosen_group}'):
            new_values = {}
            current_sig = group_signature(chosen_group)
            current_map = result_map_from_signature(current_sig)

            for a, b in MATCHES[chosen_group]:
                score = get_score_from_group_map(current_map, a, b)
                current = '未录入' if score is None else result_text(score[0], score[1])
                val = st.selectbox(
                    f'{a}  vs  {b}',
                    RESULT_OPTIONS,
                    index=RESULT_OPTIONS.index(current),
                    key=f'input_{chosen_group}_{a}_{b}',
                )
                new_values[(a, b)] = val

            c1, c2 = st.columns(2)
            submitted = c1.form_submit_button('保存本组赛果', use_container_width=True)
            cleared = c2.form_submit_button('清空本组赛果', use_container_width=True)

            if submitted:
                for a, b in MATCHES[chosen_group]:
                    key = match_key(chosen_group, a, b)
                    score = parse_result_text(new_values[(a, b)])
                    if score is None:
                        data['results'].pop(key, None)
                    else:
                        sa, sb = score
                        data['results'][key] = {'a': sa, 'b': sb}
                data['draw_positions'] = []
                save_current_data()
                st.success(f'{chosen_group} 赛果已保存')
                st.rerun()

            if cleared:
                for a, b in MATCHES[chosen_group]:
                    data['results'].pop(match_key(chosen_group, a, b), None)
                data['draw_positions'] = []
                save_current_data()
                st.success(f'{chosen_group} 赛果已清空')
                st.rerun()

elif page == '小组积分榜':
    st.subheader('小组实时积分榜')
    st.caption('排序规则：积分 → 相互战绩 → 净胜局 → 总胜局；若仍完全并列，展示顺序仅用于表格稳定。')
    chosen_group = st.selectbox('选择小组', list(GROUPS.keys()), key='table_group')
    df, ranking, _ = get_group_table(chosen_group)

    def highlight_top2(row):
        return ['background-color: #d9f2d9'] * len(row) if row['名次'] <= 2 else [''] * len(row)

    st.dataframe(df.style.apply(highlight_top2, axis=1), use_container_width=True)
    st.write(f'当前出线区：**{ranking[0]}、{ranking[1]}**')
    st.markdown('### 对阵矩阵')
    st.dataframe(get_group_matrix(chosen_group), use_container_width=True)

elif page == '出线率预测':
    st.subheader('精确出线率预测')
    st.caption('已修正并列跨线分摊逻辑：默认所有人强度相同且未开赛时，4人组每人出线率严格为 50%。')

    chosen_group = st.selectbox('选择小组', list(GROUPS.keys()), key='prob_group')

    if is_editor():
        with st.expander('调整预测强度（仅录分员可修改）', expanded=False):
            changed = False
            for player in GROUPS[chosen_group]:
                new_val = st.number_input(
                    player,
                    min_value=0.1,
                    max_value=10.0,
                    step=0.1,
                    value=float(strengths.get(player, 1.0)),
                    key=f'strength_{chosen_group}_{player}',
                )
                if abs(new_val - float(strengths.get(player, 1.0))) > 1e-9:
                    strengths[player] = float(new_val)
                    changed = True
            c1, c2 = st.columns(2)
            if c1.button('保存强度设置', use_container_width=True):
                save_current_data()
                st.success('已保存')
                st.rerun()
            if c2.button('恢复本组默认强度', use_container_width=True):
                for player in GROUPS[chosen_group]:
                    strengths[player] = 1.0
                save_current_data()
                st.success('已恢复默认')
                st.rerun()
    else:
        st.info('你当前为只读模式，只能查看出线率，不能修改预测强度。')

    qualify_prob, first_prob = get_group_probabilities(chosen_group)
    df_rank, ranking, _ = get_group_table(chosen_group)

    rows = []
    for player in GROUPS[chosen_group]:
        q = qualify_prob[player]
        f = first_prob[player]
        current_row = df_rank[df_rank['选手'] == player].iloc[0]
        if abs(q - 1.0) < 1e-12:
            status = '已锁定出线'
        elif abs(q - 0.0) < 1e-12:
            status = '理论上已出局'
        else:
            status = '待定'
        rows.append({
            '选手': player,
            '当前积分': int(current_row['积分']),
            '当前名次': int(current_row['名次']),
            '小组第一概率': f'{f * 100:.1f}%',
            '出线概率': f'{q * 100:.1f}%',
            '状态': status,
        })

    prob_df = pd.DataFrame(rows).sort_values(by=['出线概率', '小组第一概率'], ascending=False)
    st.dataframe(prob_df, use_container_width=True)
    for player in GROUPS[chosen_group]:
        st.progress(float(qualify_prob[player]), text=f'{player}：出线概率 {qualify_prob[player] * 100:.1f}%')

elif page == '第二阶段抽签':
    st.subheader('第二阶段抽签落位')
    st.caption('当前先提供 10 名出线选手随机落到 1~10 号签位。')
    qdf = qualified_players_df(results)
    st.dataframe(qdf, use_container_width=True)

    if all_matches_finished(results):
        st.success('小组赛已全部结束，可以生成第二阶段签位。')
        if not is_editor():
            st.warning('你当前是只读模式，只能查看签位，不能重新抽签。')

        if is_editor():
            c1, c2 = st.columns(2)
            if c1.button('生成/重新抽签', use_container_width=True):
                rows = qdf.to_dict('records')
                random.shuffle(rows)
                data['draw_positions'] = [
                    {'签位': idx, '选手': row['选手'], '来源': f"{row['小组']}{row['组内名次']}名"}
                    for idx, row in enumerate(rows, start=1)
                ]
                save_current_data()
                st.success('第二阶段签位已生成')
                st.rerun()
            if c2.button('清空签位', use_container_width=True):
                data['draw_positions'] = []
                save_current_data()
                st.success('签位已清空')
                st.rerun()

        if data.get('draw_positions'):
            st.markdown('### 第二阶段签位表')
            st.dataframe(pd.DataFrame(data['draw_positions']), use_container_width=True)
    else:
        st.info('小组赛尚未全部结束，暂时不能生成正式签位。')

elif page == '系统设置':
    st.subheader('系统设置')
    st.write('默认规则：每场三局两胜，赢一场 2 分，输一场 0 分，小组前 2 名出线。')

    st.markdown('### 数据文件')
    st.code(DATA_FILE)

    if is_editor():
        c1, c2 = st.columns(2)
        if c1.button('重置所有赛果', type='secondary', use_container_width=True):
            reset_results()
            st.success('已清空全部赛果')
            st.rerun()
        if c2.button('重置全部预测强度', type='secondary', use_container_width=True):
            reset_strengths()
            st.success('已恢复全部选手强度为 1.0')
            st.rerun()
    else:
        st.info('你当前是只读模式，不能执行重置操作。')

    json_text = json.dumps(data, ensure_ascii=False, indent=2)
    st.download_button('下载当前数据 JSON', data=json_text, file_name=DATA_FILE, mime='application/json')

st.divider()
st.markdown(
    '''
**本版特点**

- 只渲染当前页面，减少整页负担。  
- 积分榜 / 对阵矩阵 / 出线率做了缓存。  
- 录分用 `form` 提交，避免每点一次控件都重算。  
- 只有指定账号能改比分；其他人默认只读观看。  
- 已修复初始概率对称性问题：默认等强且未开赛时，每人出线率 50.0%。
'''
)
