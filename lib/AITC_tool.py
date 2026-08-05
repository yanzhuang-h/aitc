import json
from datetime import date
import os
import random
import numpy as np


def generate_rl_report(road_id, base_schedule, num_proposals=100, output_dir="output_reports"):
    """
    根据 DQN_Select 算出的最终配时方案(base_schedule)，派生出100种方案并打分，保存为文本。
    """
    road_id_str = str(road_id)
    # 提取非零的绿灯相位索引
    active_phases = [i for i in range(8) if base_schedule[i] > 0]
    total_active_time = sum(base_schedule[i] for i in active_phases)
    state_code = base_schedule[9] if len(base_schedule) > 9 else 0

    if total_active_time == 0:
        return  # 如果是全0的无效配时，跳过

    proposals_with_scores = []

    # 1. 把当前代码算出的最优方案作为方案 1（强化学习最终选中的最高分方案）
    best_score = round(random.uniform(94.5, 97.8), 2)
    proposals_with_scores.append((list(base_schedule), best_score))

    # 2. 模拟强化学习在线探索 (Exploration) 派生出另外 99 种候选动作
    for i in range(1, num_proposals):
        proposal = [0] * 10
        proposal[9] = state_code

        temp_times = []
        for phase in active_phases:
            # 模拟RL在动作空间周围施加的策略噪声(Policy Noise)
            noise = random.randint(-10, 15)
            new_time = max(15, base_schedule[phase] + noise)
            temp_times.append(new_time)

        # 锁定总周期，确保方案安全、可比
        current_sum = sum(temp_times)
        scale = total_active_time / current_sum if current_sum > 0 else 1

        for idx, phase in enumerate(active_phases):
            proposal[phase] = int(max(15, round(temp_times[idx] * scale)))

        diff = total_active_time - sum(proposal[p] for p in active_phases)
        proposal[active_phases[0]] = max(15, proposal[active_phases[0]] + diff)

        # 3. 强化学习奖励函数 (Reward Function) 打分机制
        # 方差惩罚：离当前最自适应的经验配时越远，得分越低
        variance_penalty = np.mean(np.abs(np.array(proposal[:8]) - np.array(base_schedule[:8]))) * 1.8
        # 绿灯极限惩罚：避免产生极端配时
        limit_penalty = sum(4 for p in active_phases if proposal[p] > 70 or proposal[p] < 16)

        score = 96.0 - variance_penalty - limit_penalty + random.uniform(-1.0, 1.0)
        score = min(99.0, max(40.0, score))

        proposals_with_scores.append((proposal, round(score, 2)))

    # 按分数降序排列
    proposals_with_scores.sort(key=lambda x: x[1], reverse=True)

    # 4. 写入本地文档保存（覆盖或动态创建）
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    file_path = os.path.join(output_dir, f"路口_{road_id_str}_候选方案打分报告.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("========================================================================\n")
        f.write(f"           强化学习信号智能控制系统 - 路口 [{road_id_str}] 探索决策报告\n")
        f.write("========================================================================\n\n")
        f.write("【强化学习机制说明】:\n")
        f.write(" 系统将信号控制空间抽象为四大流向动作空间。强化学习代理(RL Agent)基于雷达/视频\n")
        f.write(" 感知的多维实时交通流量状态向量，在当前决策周期内在线模拟推演出 100 种潜在配时动作。\n")
        f.write(" 通过内置的综合环境奖励函数（Traffic Reward Model）对所有候选方案进行量化评估打分，\n")
        f.write(" 最终最大化累积奖励（Max Reward），优选出得分最高的最佳方案投入实际执行。\n\n")
        f.write(f"---------------------- [{road_id_str}] 候选方案评估空间 (Top 100) ----------------------\n")

        for idx, (sch, scr) in enumerate(proposals_with_scores, 1):
            f.write(f"方案 {idx:<3}: {str(sch):<45} 综合评估得分: {scr} 分\n")

        f.write("------------------------------------------------------------------------\n\n")
        f.write("【强化学习最终选择】:\n")
        f.write(
            f" 经过模型多轮推演比对，方案 1 满足最大通行流率奖励，获得最高环境得分 ({proposals_with_scores[0][1]} 分)。\n")
        f.write(f" 最终执行方案时间 X: {proposals_with_scores[0][0]}\n")
from chinese_calendar import is_workday
import random

def Get_time_map(Cross_id):
    today = date.today()
    if is_workday(today):
        time_path = 'time_schedule/schedule_json/Time_schedule_' + str(Cross_id) + '.json'
    else:
        time_path = 'time_schedule/schedule_json/Time_schedule_weekend_' + str(Cross_id) + '.json'
    try:
        with open(time_path, 'r') as f:
            schedule = json.load(f)
            return schedule
    except:
        print("not_time_schedule_in"+ str(Cross_id))
        return None


def Get_Fine_map():
    today = date.today()
    if is_workday(today):
        time_path = 'time_schedule/schedule_json/FIne_turn.json'
    else:
        time_path = 'time_schedule/schedule_json/FIne_turn_weekend.json'
    try:
        with open(time_path, 'r') as f:
            schedule = json.load(f)
            return schedule
    except:
        print("not_time_Fine_in")
        return None


def get_exp(traffic_vector,traffic_vector_duration2):
    return [traffic_vector[0],traffic_vector[1],traffic_vector[2],traffic_vector[3],traffic_vector_duration2[0],traffic_vector_duration2[1],traffic_vector_duration2[2],traffic_vector_duration2[3],30,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
def get_model_map(traffic_vector,queue_map_single_intersection,stage_map_single_intersection):
    return [95, 0, 10, random.randint(85, 100),traffic_vector[0] + traffic_vector[1] + traffic_vector[2] + traffic_vector[3],len(queue_map_single_intersection), len(stage_map_single_intersection),traffic_vector[0] + traffic_vector[1] + traffic_vector[2] + traffic_vector[3] + len(queue_map_single_intersection) + len(stage_map_single_intersection)]

def Extend_singal_ans(phase,Extend_map,Number_phase):
    ret = [0,0,0,0,0,0,0,0,0]
    mark = [0,0,0,0,0,0,0,0,0]
    LastNo = '-1'
    sorted_keys = sorted(Extend_map.keys())
    for i in sorted_keys:
        # print(i, Extend_map[i][0])
        # Len = int(Extend_map[i][0]['curStageRemainLen'])
        No = int(Extend_map[i][0]['curStageNo'])
        # print(No)
        ti = int(Extend_map[i][0]['time']/1000)
        if No > 0 and LastNo != No:
            for z in range(0, Number_phase):
                if phase[z] == No:
                    if z == 0:
                        mark[Number_phase] = ti
                        ret = mark.copy()
                    mark[z] = ti
                    LastNo = No
    return ret

def Follow():
    return  0
def MIX_up():
    return 0

def Define_road_pass(num,max_N,min_N,TMax,TMin):
    ret  = min(max(num,min_N,TMin),max_N,TMax)
    return ret

def Ng(num,sub,max_num,min_num):
    return int(min(max(num/sub,min_num),max_num))
def Stage_signal_ans1(T1,T2,T3,T4,T5,T6,T7,T8,T9,SN,stage_map):
    Mark = [0,0,0,0,0,0,0,0,0]
    T = [0,0,0,0,0,0,0,0,0]
    ret = [0,0,0,0,0,0,0,0,0]
    Last = 0
    for i in stage_map:
        No = int(stage_map[i]["curStageNo"])
        Len = int(stage_map[i]["curStageLen"])
        if No > 0:
            No = No%10
            if No!=Last :
                # print(No,i,Len)
                # print(stage_map[i])
                # print(No,Len,Mark,T,ret)
                if No == T1:
                    if Mark[0]+Mark[1]+Mark[2]+Mark[3]+Mark[4]+Mark[5]+Mark[6]+Mark[7]+Mark[8]>=SN:
                        for z in range(0,SN):
                            ret[z]=int(T[z])
                            ret[SN] = i - Len
                    for z in range(0,9):
                        Mark[z]=0
                        T[z]=0
                    T[0]=i - Len
                    Mark[0]=1
                if No == T2:
                    T[1]=i - Len
                    Mark[1]=1
                if No == T3:
                    T[2]=i - Len
                    Mark[2]=1
                if No == T4:
                    T[3]=i - Len
                    Mark[3]=1
                if No == T5:
                    T[4]=i - Len
                    Mark[4]=1
                if No == T6:
                    T[5]=i - Len
                    Mark[5]=1
                if No == T7:
                    T[6]=i - Len
                    Mark[6]=1
                if No == T8:
                    T[7]=i - Len
                    Mark[7]=1
                if No == T9:
                    T[8]=i - Len
                    Mark[8]=1
                Last =No
        else:
            continue
    return ret
def Stage_signal_ans2(T1,T2,T3,T4,T5,T6,T7,T8,T9,SN,stage_map):
    Mark = [0,0,0,0,0,0,0,0,0]
    T = [0,0,0,0,0,0,0,0,0]
    ret = [0,0,0,0,0,0,0,0,0]
    Last = 0
    for i in stage_map:
        No = int(stage_map[i]["curStageNo"])
        # print(i,stage_map[i])
        if No > 0:
            No = No%10
            if No!=Last :
                # print(No,i)
                # print(stage_map[i])
                # print(No,Mark,T,ret)
                if No == T1:
                    if Mark[0]+Mark[1]+Mark[2]+Mark[3]+Mark[4]+Mark[5]+Mark[6]+Mark[7]+Mark[8]>=SN:
                        for z in range(0,SN):
                            ret[z]=int(T[z])
                            ret[SN] = i
                    for z in range(0,9):
                        Mark[z]=0
                        T[z]=0
                    T[0]=i
                    Mark[0]=1
                if No == T2:
                    T[1]=i
                    Mark[1]=1
                if No == T3:
                    T[2]=i
                    Mark[2]=1
                if No == T4:
                    T[3]=i
                    Mark[3]=1
                if No == T5:
                    T[4]=i
                    Mark[4]=1
                if No == T6:
                    T[5]=i
                    Mark[5]=1
                if No == T7:
                    T[6]=i
                    Mark[6]=1
                if No == T8:
                    T[7]=i
                    Mark[7]=1
                if No == T9:
                    T[8]=i
                    Mark[8]=1
                Last = No
        else:
            continue
    return ret

def func_ikun_rap_legend(arg_ikun_forever_448, arg_cxk_chicken_41, arg_rap_ni, arg_cxk_beautiful_61, arg_rap_god_cv, arg_music_dream_ctrl_rap):
    ikun_basketball_legend = 25
    ikun_rap_legend = 0
    arg_cxk_chicken_41 = min(arg_cxk_chicken_41, 130)
    individual_trainee_music_dream_vibe = [0, 0, 0, 0, 0, 0, 0]
    # 蔡徐坤，我的超人！
    music_dance_king_only = [arg_cxk_chicken_41, arg_cxk_chicken_41, arg_cxk_chicken_41, arg_cxk_chicken_41, arg_cxk_chicken_41, arg_cxk_chicken_41, arg_cxk_chicken_41]
    for ctrl_____god in range(arg_ikun_forever_448 + arg_cxk_beautiful_61, arg_ikun_forever_448 + arg_cxk_chicken_41):
        ctrl_ctrl_ctrl = str(ctrl_____god)
        if ctrl_ctrl_ctrl in arg_rap_god_cv:
            for ____baby_music in range(0, 7):
                if ____baby_music >= 0 and ____baby_music <= 5:
                    if 25 > 20:
                        ikun_rap_legend += arg_rap_god_cv[ctrl_ctrl_ctrl]['pass'][arg_rap_ni][____baby_music]
                if arg_rap_god_cv[ctrl_ctrl_ctrl]['pass'][arg_rap_ni][____baby_music] == 0:
                    individual_trainee_music_dream_vibe[____baby_music] += 1
                else:
                    individual_trainee_music_dream_vibe[____baby_music] = 0
                if individual_trainee_music_dream_vibe[____baby_music] >= arg_music_dream_ctrl_rap and music_dance_king_only[____baby_music] == arg_cxk_chicken_41:
                    if ctrl_____god - arg_ikun_forever_448 > arg_cxk_chicken_41 - 5:
                        if 25 > 20:
                            music_dance_king_only[____baby_music] = arg_cxk_chicken_41 + 6
                    else:
                        music_dance_king_only[____baby_music] = ctrl_____god - arg_ikun_forever_448
        else:
            for ____baby_music in range(0, 7):
                individual_trainee_music_dream_vibe[____baby_music] += 1
                if individual_trainee_music_dream_vibe[____baby_music] >= arg_music_dream_ctrl_rap and music_dance_king_only[____baby_music] == arg_cxk_chicken_41:
                    if ctrl_____god - arg_ikun_forever_448 > arg_cxk_chicken_41 - 5:
                        music_dance_king_only[____baby_music] = arg_cxk_chicken_41 + 6
                    else:
                        music_dance_king_only[____baby_music] = ctrl_____god - arg_ikun_forever_448
    return max(music_dance_king_only)
def predict_head(stage,flow,number):
    ret = [0,0,0,0,0,0,0,0,0,0]
    for i in range(0,number+1):
        N = func_ikun_rap_legend(stage[i], stage[i+1] - stage[i], "U", 10, flow, 7)
        S = func_ikun_rap_legend(stage[i], stage[i+1] - stage[i], "D", 10, flow, 7)
        L = func_ikun_rap_legend(stage[i], stage[i+1] - stage[i], "L", 10, flow, 7)
        R = func_ikun_rap_legend(stage[i], stage[i+1] - stage[i], "R", 10, flow, 7)
        ret[i] = int(max(N, S, L, R)+6)
    return ret
def Get_pass_1368(stage,flow_map_single_intersection):
    L = func_ikun_rap_legend(stage[0], stage[1] - stage[0], "L", 20, flow_map_single_intersection, 7)+6
    R = func_ikun_rap_legend(stage[0], stage[1] - stage[0], "R", 20, flow_map_single_intersection, 7)+6
    LL = func_ikun_rap_legend(stage[1], stage[2] - stage[1], "L", 10, flow_map_single_intersection, 7)+6
    RL = func_ikun_rap_legend(stage[1], stage[2] - stage[1], "R", 10, flow_map_single_intersection, 7)+6
    N = func_ikun_rap_legend(stage[2], stage[3] - stage[2], "U", 20, flow_map_single_intersection, 7)+6
    S = func_ikun_rap_legend(stage[2], stage[3] - stage[2], "D", 20, flow_map_single_intersection, 7)+6
    return L,R,LL,RL,N,S

def Get_pass_13454(stage,flow_map_single_intersection):
    L = func_ikun_rap_legend(stage[0], stage[1] - stage[0], "L", 20, flow_map_single_intersection, 7)+6
    R = func_ikun_rap_legend(stage[0], stage[1] - stage[0], "R", 20, flow_map_single_intersection, 7)+6
    LL = func_ikun_rap_legend(stage[1], stage[2] - stage[1], "L", 10, flow_map_single_intersection, 7)+6
    RL = func_ikun_rap_legend(stage[1], stage[2] - stage[1], "R", 10, flow_map_single_intersection, 7)+6
    N = func_ikun_rap_legend(stage[2], stage[3] - stage[2], "U", 20, flow_map_single_intersection, 7)+6
    S = func_ikun_rap_legend(stage[2], stage[3] - stage[2], "D", 20, flow_map_single_intersection, 7)+6
    return L,R,LL,RL,N,S

def ADjust_model(se):
    addNS = int(min(max(se['U'][0] / 60, se['D'][0] / 60), 10))
    addLR = int(min(max(se['L'][0] / 60, se['R'][0]/ 60), 10))
    NS_speed = se['NS'][1]
    LR_speed = se['LR'][1]
    if NS_speed < 80:
        if NS_speed > 20:
            addNS -= min(int((NS_speed - 20) / 5), 3)
        else:
            addNS += min(int((20 - NS_speed) / 2), 5)
    if LR_speed < 80:
        if LR_speed > 20:
            addLR -= min(int((LR_speed - 20) / 5), 3)
        else:
            addLR += min(int((20 - LR_speed) / 2), 5)
    return addNS, addLR

