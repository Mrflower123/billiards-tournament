import json
import os
import random
from copy import deepcopy
from itertools import combinations

import pandas as pd
import streamlit as st

st.set_page_config(page_title='台球比赛积分管理', layout='wide')

DATA_FILE = 'billiards_tournament_data.json'

# 说明：名单我先按图片录入；如果其中个别字与你们实际名单不一致，
# 直接改这里的 GROUPS 即可，其他逻辑不需要改。
GROUPS = {
    'A组': ['白云峰', '程云喜', '赵国强', '刘士伟'],
    'B组': ['张太忠', '孙孝沅', '齐宝奎', '耿旭'],
    'C组': ['耿桢', '程谟臣', '李健', '赵磊'],
    'D组': ['尹家林', '刘祥', '赵洪伟', '王绪东'],
    'E组': ['邹贤盛', '毕庶安', '陈凤瑞', '付延菁'],
}

WIN_POINTS = 2
LOSS_POINTS = 0
RESULT_OPTIONS = ['未录入', '2:0', '2:1', '1:2', '0:2']

MATCHES = {
    group: list(combinations(players, 2))
    for group, players in GROUPS.items()
}


# -------------------- 数据读写 --------------------
def default_strengths():
    strengths = {}
    for players in GROUPS.values():
        for p in players:
            strengths[p] = 1.0
    return strengths


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}

    data.setdefault('results', {})
    data.setdefault('strengths', {})
    data.setdefault('draw_positions', [])

    for player, value in default_strengths().items():
        data['strengths'].setdefault(player, value)

    return data


def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -------------------- 基础工具 --------------------
def match_key(group, a, b):
    return f'{group}|{a}|{b}'


def parse_result_text(text):
    if text == '未录入':
        return None
    a, b = text.split(':')
    return int(a), int(b)


def result_text(score_a, score_b):
    return f'{score_a}:{score_b}'


def validate_best_of_three(score_a, score_b):
    return (score_a, score_b) in {(2, 0), (2, 1), (1, 2), (0, 2)}


def init_stats(players):
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


def apply_match(stats, a, b, score_a, score_b):
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



def get_group_results(all_results, group):
    results = {}
    for a, b in MATCHES[group]:
        key = match_key(group, a, b)
        if key in all_results:
            results[key] = all_results[key]
    return results



def get_group_stats(group, all_results):
    players = GROUPS[group]
    stats = init_stats(players)
    for a, b in MATCHES[group]:
        key = match_key(group, a, b)
        if key in all_results:
            score_a = int(all_results[key]['a'])
            score_b = int(all_results[key]['b'])
            apply_match(stats, a, b, score_a, score_b)
    return stats



def mini_league_stats(group, all_results, subset_players):
    stats = init_stats(subset_players)
    subset = set(subset_players)
    for a, b in MATCHES[group]:
        if a in subset and b in subset:
            key = match_key(group, a, b)
            if key in all_results:
                score_a = int(all_results[key]['a'])
                score_b = int(all_results[key]['b'])
                apply_match(stats, a, b, score_a, score_b)
    return stats



def break_tie(group, all_results, tied_players, overall_stats):
    """
    平分时的排序规则：
    1. 平分选手之间的相互战绩积分
    2. 平分选手之间的净胜局
    3. 平分选手之间的总胜局
    4. 全组净胜局
    5. 全组总胜局
    6. 姓名（仅作为最终稳定排序兜底）
    """
    mini_stats = mini_league_stats(group, all_results, tied_players)

    def sort_key(player):
        return (
            -mini_stats[player]['积分'],
            -mini_stats[player]['净胜局'],
            -mini_stats[player]['胜局'],
            -overall_stats[player]['净胜局'],
            -overall_stats[player]['胜局'],
            player,
        )

    return sorted(tied_players, key=sort_key)



def rank_group(group, all_results):
    stats = get_group_stats(group, all_results)
    players = GROUPS[group]

    point_buckets = {}
    for p in players:
        point_buckets.setdefault(stats[p]['积分'], []).append(p)

    ordered_players = []
    for pts in sorted(point_buckets.keys(), reverse=True):
        tied = point_buckets[pts]
        if len(tied) == 1:
            ordered_players.extend(tied)
        else:
            ordered_players.extend(break_tie(group, all_results, tied, stats))

    rows = []
    for rank_idx, player in enumerate(ordered_players, start=1):
        row = dict(stats[player])
        row['名次'] = rank_idx
        rows.append(row)

    df = pd.DataFrame(rows)[['名次', '选手', '场次', '胜场', '负场', '积分', '胜局', '负局', '净胜局']]
    return df, ordered_players, stats


# -------------------- 出线率精确计算 --------------------
def winner_prob(strength_a, strength_b):
    total = max(strength_a, 0.0) + max(strength_b, 0.0)
    if total <= 0:
        return 0.5
    return max(strength_a, 0.0) / total



def sweep_prob(p_match_win):
    # 胜者 2:0 的概率。强弱差越大，横扫概率越高。
    # 取值大约在 0.35 ~ 0.80 之间。
    return min(0.80, max(0.35, 0.35 + abs(p_match_win - 0.5)))



def outcome_distribution(a, b, strengths):
    sa = strengths.get(a, 1.0)
    sb = strengths.get(b, 1.0)
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



def exact_group_advancement_prob(group, all_results, strengths):
    players = GROUPS[group]
    group_results = get_group_results(all_results, group)
    remaining = []
    for a, b in MATCHES[group]:
        key = match_key(group, a, b)
        if key not in group_results:
            remaining.append((a, b))

    qualify_prob = {p: 0.0 for p in players}
    first_prob = {p: 0.0 for p in players}

    # 没有剩余比赛，直接给出确定结果
    if not remaining:
        _, ranking, _ = rank_group(group, group_results)
        first_prob[ranking[0]] = 1.0
        qualify_prob[ranking[0]] = 1.0
        qualify_prob[ranking[1]] = 1.0
        return qualify_prob, first_prob

    def dfs(idx, scenario_results, current_prob):
        if idx == len(remaining):
            _, ranking, _ = rank_group(group, scenario_results)
            first_prob[ranking[0]] += current_prob
            qualify_prob[ranking[0]] += current_prob
            qualify_prob[ranking[1]] += current_prob
            return

        a, b = remaining[idx]
        key = match_key(group, a, b)
        for (score_a, score_b), p in outcome_distribution(a, b, strengths):
            next_results = dict(scenario_results)
            next_results[key] = {'a': score_a, 'b': score_b}
            dfs(idx + 1, next_results, current_prob * p)

    dfs(0, group_results, 1.0)

    # 数值误差校正
    for p in players:
        qualify_prob[p] = max(0.0, min(1.0, qualify_prob[p]))
        first_prob[p] = max(0.0, min(1.0, first_prob[p]))

    return qualify_prob, first_prob


# -------------------- 展示工具 --------------------
def all_matches_finished(all_results):
    total_matches = sum(len(v) for v in MATCHES.values())
    return len(all_results) == total_matches



def qualified_players(all_results):
    qualifiers = []
    for group in GROUPS:
        df, ranking, _ = rank_group(group, all_results)
        qualifiers.append({'小组': group, '组内名次': 1, '选手': ranking[0]})
        qualifiers.append({'小组': group, '组内名次': 2, '选手': ranking[1]})
    return pd.DataFrame(qualifiers)



def render_group_matrix(group, all_results):
    players = GROUPS[group]
    matrix = pd.DataFrame('', index=players, columns=players)
    for p in players:
        matrix.loc[p, p] = '—'

    for a, b in MATCHES[group]:
        key = match_key(group, a, b)
        if key in all_results:
            sa = all_results[key]['a']
            sb = all_results[key]['b']
            matrix.loc[a, b] = f'{sa}:{sb}'
            matrix.loc[b, a] = f'{sb}:{sa}'
        else:
            matrix.loc[a, b] = '待赛'
            matrix.loc[b, a] = '待赛'

    st.dataframe(matrix, use_container_width=True)


# -------------------- 页面主体 --------------------
data = load_data()
results = data['results']
strengths = data['strengths']

st.title('🎱 台球比赛积分管理小程序')
st.caption('支持：赛果录入、积分榜实时更新、精确出线率预测、第二阶段抽签落位。')

with st.sidebar:
    st.header('基础设置')
    st.write('默认规则：每场三局两胜，赢一场 2 分，输一场 0 分，小组前 2 名出线。')

    if st.button('重置所有赛果', type='secondary'):
        data['results'] = {}
        data['draw_positions'] = []
        save_data(data)
        st.success('已清空全部赛果。请刷新页面。')

    if st.button('重置预测强度', type='secondary'):
        data['strengths'] = default_strengths()
        save_data(data)
        st.success('已把所有选手强度恢复为 1.0。请刷新页面。')

    st.divider()
    st.subheader('预测强度设置')
    st.caption('用于计算“出线率”。全部保持 1.0 时，等价于默认人人五五开。')

    changed = False
    for group, players in GROUPS.items():
        with st.expander(group, expanded=False):
            for player in players:
                new_val = st.number_input(
                    f'{player}',
                    min_value=0.1,
                    max_value=10.0,
                    step=0.1,
                    value=float(data['strengths'].get(player, 1.0)),
                    key=f'strength_{group}_{player}',
                )
                if abs(new_val - float(data['strengths'].get(player, 1.0))) > 1e-9:
                    data['strengths'][player] = float(new_val)
                    changed = True

    if changed:
        save_data(data)

    st.divider()
    st.subheader('数据文件')
    st.code(DATA_FILE)

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with open(DATA_FILE, 'rb') as f:
        st.download_button(
            label='下载当前数据 JSON',
            data=f,
            file_name=DATA_FILE,
            mime='application/json',
        )

# 统计概览
col1, col2, col3, col4 = st.columns(4)
total_matches = sum(len(v) for v in MATCHES.values())
finished_matches = len(results)
qualified_now = []
for g in GROUPS:
    _, ranking, _ = rank_group(g, results)
    qualified_now.extend(ranking[:2])

col1.metric('总场次', total_matches)
col2.metric('已完赛', finished_matches)
col3.metric('待进行', total_matches - finished_matches)
col4.metric('当前暂列出线区人数', len(qualified_now))


tab1, tab2, tab3, tab4 = st.tabs(['赛果录入', '小组积分榜', '出线率预测', '第二阶段抽签'])

# -------------------- Tab 1 赛果录入 --------------------
with tab1:
    st.subheader('录入或修改比赛结果')
    st.write('每个小组共 6 场比赛。比分只能填：2:0、2:1、1:2、0:2。')

    for group in GROUPS:
        with st.expander(f'{group} 赛果录入', expanded=(group == 'A组')):
            with st.form(f'form_{group}'):
                new_values = {}
                for a, b in MATCHES[group]:
                    key = match_key(group, a, b)
                    if key in results:
                        current = result_text(results[key]['a'], results[key]['b'])
                    else:
                        current = '未录入'

                    val = st.selectbox(
                        f'{a}  vs  {b}',
                        RESULT_OPTIONS,
                        index=RESULT_OPTIONS.index(current),
                        key=f'input_{group}_{a}_{b}',
                    )
                    new_values[key] = val

                c1, c2 = st.columns(2)
                submitted = c1.form_submit_button('保存本组赛果', use_container_width=True)
                clear_group = c2.form_submit_button('清空本组赛果', use_container_width=True)

                if submitted:
                    for key, val in new_values.items():
                        score = parse_result_text(val)
                        if score is None:
                            data['results'].pop(key, None)
                        else:
                            score_a, score_b = score
                            data['results'][key] = {'a': score_a, 'b': score_b}
                    data['draw_positions'] = []
                    save_data(data)
                    st.success(f'{group} 赛果已保存。')

                if clear_group:
                    for a, b in MATCHES[group]:
                        key = match_key(group, a, b)
                        data['results'].pop(key, None)
                    data['draw_positions'] = []
                    save_data(data)
                    st.success(f'{group} 赛果已清空。')

            st.markdown('**当前对阵矩阵**')
            render_group_matrix(group, data['results'])

# -------------------- Tab 2 积分榜 --------------------
with tab2:
    st.subheader('小组实时积分榜')
    st.caption('排序规则：积分 → 相互战绩 → 净胜局 → 总胜局。')

    for group in GROUPS:
        df, ranking, _ = rank_group(group, data['results'])
        st.markdown(f'### {group}')

        def highlight_top2(row):
            if row['名次'] <= 2:
                return ['background-color: #d9f2d9'] * len(row)
            return [''] * len(row)

        st.dataframe(df.style.apply(highlight_top2, axis=1), use_container_width=True)
        st.write(f'当前出线区：**{ranking[0]}、{ranking[1]}**')
        render_group_matrix(group, data['results'])
        st.divider()

# -------------------- Tab 3 出线率 --------------------
with tab3:
    st.subheader('精确出线率预测')
    st.caption('这里不是随机模拟，而是把本组剩余比赛全部枚举后得到的精确概率。')
    st.caption('如果你不调整左侧“预测强度”，系统默认所有人实力相同。')

    for group in GROUPS:
        qualify_prob, first_prob = exact_group_advancement_prob(group, data['results'], data['strengths'])
        df_rank, ranking, _ = rank_group(group, data['results'])

        rows = []
        for player in GROUPS[group]:
            q = qualify_prob[player]
            f = first_prob[player]
            if abs(q - 1.0) < 1e-9:
                status = '已锁定出线'
            elif abs(q - 0.0) < 1e-9:
                status = '理论上已出局'
            else:
                status = '待定'
            rows.append({
                '选手': player,
                '当前积分': int(df_rank[df_rank['选手'] == player]['积分'].iloc[0]),
                '当前名次': int(df_rank[df_rank['选手'] == player]['名次'].iloc[0]),
                '小组第一概率': f'{f * 100:.1f}%',
                '出线概率': f'{q * 100:.1f}%',
                '状态': status,
            })

        st.markdown(f'### {group}')
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        for player in GROUPS[group]:
            st.progress(float(qualify_prob[player]), text=f'{player}：出线概率 {qualify_prob[player] * 100:.1f}%')
        st.divider()

# -------------------- Tab 4 第二阶段抽签 --------------------
with tab4:
    st.subheader('第二阶段抽签落位')
    st.caption('这里先做成“10 名出线选手随机抽签到 1~10 号签位”。如果你后面确定了第二阶段赛制，我可以再给你扩成淘汰赛/双败/循环赛版本。')

    current_qualifiers = qualified_players(data['results'])
    st.markdown('### 当前暂定出线名单')
    st.dataframe(current_qualifiers, use_container_width=True)

    if all_matches_finished(data['results']):
        st.success('小组赛已经全部结束，可以生成第二阶段签位。')
        c1, c2 = st.columns(2)

        if c1.button('生成/重新抽签', use_container_width=True):
            rows = current_qualifiers.to_dict('records')
            random.shuffle(rows)
            data['draw_positions'] = [
                {
                    '签位': idx,
                    '选手': row['选手'],
                    '来源': f"{row['小组']}{row['组内名次']}名",
                }
                for idx, row in enumerate(rows, start=1)
            ]
            save_data(data)
            st.success('第二阶段签位已生成。')

        if c2.button('清空签位', use_container_width=True):
            data['draw_positions'] = []
            save_data(data)
            st.success('已清空第二阶段签位。')

        if data.get('draw_positions'):
            st.markdown('### 第二阶段签位表')
            st.dataframe(pd.DataFrame(data['draw_positions']), use_container_width=True)
    else:
        st.info('小组赛尚未全部结束，暂时不能生成正式签位。')

st.divider()
st.markdown(
    '''
**后续还能继续扩展的内容**

1. 自动生成比赛日程表（今天打哪些场、还剩哪些场）。  
2. 接入第二阶段正式赛制，比如 10 人淘汰赛、双败赛、或再分组循环。  
3. 增加大屏展示模式，适合比赛现场投屏。  
4. 增加“选手数据页”，看每个人的胜率、2:0 次数、2:1 次数、连胜等。  
'''
)
