"""Legacy special-intersection adjustments extracted from global coordination."""

import random
import time


def apply_special_intersection_adjustments(
        result_action_map, inter_road_state, forced_aibi_roads,
        online_data_map, road_map, se_map, coordinate_map_set, hour,
        get_time_map, get_min_sub):
    """Apply legacy special-road rules in place and return the plan map."""
    current_time = int(time.time() * 1000)
    t = time.localtime(current_time / 1000)

    minute = t.tm_min
    shi = t.tm_hour

    if 1300106 in inter_road_state and result_action_map["1300106"][9] == 0:
        result_action_map["1300106"][1] += 5


    if 2703062 in inter_road_state and result_action_map["2703062"][9] == 0:
        result_action_map["2703062"][1] += 5

    if 1300103 in inter_road_state and result_action_map["1300103"][9] == 0:
        result_action_map["1300103"][1] += 8



    if 1300103 in inter_road_state and result_action_map["1300103"][9] == 0:
        result_action_map["1300103"][1] += 10
    if 1300229 in inter_road_state and result_action_map["1300229"][9] == 0:
        if (shi>=7 and shi<=10) or (shi>=17 and shi<=19):
            for i in range(10):
                if result_action_map["1300229"][i] != 0:
                    num11 = random.randint(0, 9)
                    result_action_map["1300229"][i]=result_action_map["1300229"][i]+(num11+i)%5
        else:
            for i in range(10):
                if result_action_map["1300229"][i] != 0:
                    num11 = random.randint(0, 9)
                    result_action_map["1300229"][i]=result_action_map["1300229"][i]+(num11+i)%3

    if 1700124 in inter_road_state :
        result_action_map["1700124"][0]+=3
        result_action_map["1700124"][0]=max(min(result_action_map["1700124"][0],98),40)

    if 1700125 in inter_road_state:
        result_action_map["1700125"][0] += 3
        result_action_map["1700125"][0] = max(min(result_action_map["1700125"][0], 98), 55)


    if 1700126 in inter_road_state:
        result_action_map["1700126"][0] += 3
        result_action_map["1700126"][0] = max(min(result_action_map["1700126"][0], 88), 75)

    if 1700079 in inter_road_state:
        result_action_map["1700079"][0] += 3




    if (1300870 in inter_road_state
            and 1300870 not in forced_aibi_roads
            and result_action_map["1300870"][9] == 0):
        if inter_road_state[1300870]["U"][0] > 0 and inter_road_state[1300870]["D"][0] > 0:
            addU = int((inter_road_state[1300870]["U"][1] / inter_road_state[1300870]["U"][0]) * 6)
            addD = int((inter_road_state[1300870]["D"][1] / inter_road_state[1300870]["D"][0]) * 6)
            if inter_road_state[1300870]["U"][2] > 22:
                addU = int(min(inter_road_state[1300870]["U"][2] - 22, 3))
            if inter_road_state[1300870]["U"][2] < 15:
                addU += int(min(15 - inter_road_state[1300870]["U"][2], 5))

            if inter_road_state[1300870]["D"][2] < 15:
                addD += int(min(15 - inter_road_state[1300870]["D"][2], 5))
            if inter_road_state[1300870]["D"][2] > 22:
                addD = int(min(inter_road_state[1300870]["D"][2] - 22, 3))
            if inter_road_state[1300870]["U"][3] == 1:
                result_action_map["1300870"][9] = 4
                result_action_map["1300870"][3] = int(result_action_map["1300870"][1])
                result_action_map["1300870"][2] = 20
                result_action_map["1300870"][1] = int(result_action_map["1300870"][0]) - 20 + max(addD, addU)
                result_action_map["1300870"][0] = 12

            elif inter_road_state[1300870]["D"][3] == 1:
                result_action_map["1300870"][9] = 3
                result_action_map["1300870"][2] = int(result_action_map["1300870"][1])
                result_action_map["1300870"][1] = int(result_action_map["1300870"][0]) - 18 + max(addD, addU)
                result_action_map["1300870"][0] = 18


    if (1300271 in inter_road_state
            and 1300271 not in forced_aibi_roads
            and result_action_map["1300271"][9] == 0):
        if inter_road_state[1300271]["U"][0] > 0 and inter_road_state[1300271]["D"][0] > 0:

            if inter_road_state[1300271]["U"][3] == 1 and inter_road_state[1300271]["D"][3] == 1:
                if inter_road_state[1300271]["L"][3] == 0:
                    result_action_map["1300271"][3] = max(33,result_action_map["1300271"][3]-5)
                if inter_road_state[1300271]["R"][3] == 0:
                    result_action_map["1300271"][2] = max(33, result_action_map["1300271"][2] - 5)
                result_action_map["1300271"][0]+=10

            elif inter_road_state[1300271]["U"][3] == 1:

                result_action_map["1300271"][9] = 4
                result_action_map["1300271"][4] = int(result_action_map["1300271"][3])
                result_action_map["1300271"][3] = int(result_action_map["1300271"][2])
                result_action_map["1300271"][2] = int(result_action_map["1300271"][1])
                result_action_map["1300271"][1]= int(result_action_map["1300271"][0] * 0.05 + 15)
                result_action_map["1300271"][0]=max(38,result_action_map["1300271"][3]-7)

            elif inter_road_state[1300271]["D"][3] == 1:
                result_action_map["1300271"][9] = 3
                result_action_map["1300271"][4] = int(result_action_map["1300271"][3])
                result_action_map["1300271"][3] = int(result_action_map["1300271"][2])
                result_action_map["1300271"][2] = int(result_action_map["1300271"][1])
                result_action_map["1300271"][1] = int(result_action_map["1300271"][0] * 0.05 + 15)
                result_action_map["1300271"][0] = max(38, result_action_map["1300271"][3] - 7)
            if inter_road_state[1300271]["L"][3] == 1:
                if result_action_map["1300271"][9] == 0:
                    result_action_map["1300271"[3]]+=5
                else:
                    result_action_map["1300271"][4] += 5
            if inter_road_state[1300271]["R"][3] == 1:
                if result_action_map["1300271"][9] == 0:
                    result_action_map["1300271"][2]+=5
                else:
                    result_action_map["1300271"][3] += 5
        print(result_action_map,"1300271========================")
        print("1300271========================")
    if 1700087 in inter_road_state and result_action_map["1700087"][9] == 0:
        if hour == 7 :
            result_action_map['17002087'][0] += 5
    if 1300097 in inter_road_state and result_action_map["1300097"][9] == 0:
        result_action_map["1300097"][2] +=10
    if 1700276 in inter_road_state and result_action_map["1700276"][9] == 0:
        if hour >= 7 and hour <= 20:
            result_action_map['1700276'][4]+=10

    if 2703062 in inter_road_state and result_action_map["2703062"][9] == 0:
            result_action_map['2703062'][1]=int(result_action_map['1300106'][1]*1.5)+5
    if 1300106 in inter_road_state and result_action_map["1300106"][9] == 0:
            result_action_map['1300106'][1]=int(result_action_map['1300106'][1]*2.5)+5

    if 1300397 in inter_road_state and result_action_map["1300397"][9] == 0:
        if hour >= 7 and hour <= 20:
            result_action_map['1300397'][1]+=5
    if 2708375 in inter_road_state and result_action_map["2708375"][9] == 0:
        if (hour >= 7 and hour <= 9) or (hour >= 17 and hour <= 19):
            result_action_map['2708375'][0]=result_action_map['2708375'][0]+25



    if 1700086 in inter_road_state and result_action_map["1700086"][9] == 0:
        if hour >= 7 and hour <= 20:
            result_action_map['1700086'][1]+=13
            result_action_map['1700086'][0] += 12
            result_action_map['1700086'][0]=min(65,max(result_action_map['1700086'][0],45))
            result_action_map['1700086'][2]=min(60,max(result_action_map['1700086'][2],40))
    if 1300068 in inter_road_state and result_action_map["1300068"][9] == 0:#开南单
        if inter_road_state[1300068]["R"][0] > 0 and inter_road_state[1300068]["D"][0] > 0:
            if hour>=16 and hour<=20:
                if inter_road_state[1300068]["D"][3] == 1:
                    result_action_map['1300068'][9] = 3
                    result_action_map['1300068'][3] = int(result_action_map['1300068'][2])
                    result_action_map['1300068'][2] = 16

            if result_action_map['1300068'][9] == 0:
                if inter_road_state[1300068]["R"][3] == 1:
                    if inter_road_state[1300068]["L"][3]==1:
                        result_action_map['1300068'][0] += 5
                    else:
                        result_action_map['1300068'][9] = 1
                        result_action_map['1300068'][3] = int(result_action_map['1300068'][2])
                        result_action_map['1300068'][2] = int(result_action_map['1300068'][1])
                        result_action_map['1300068'][1] = int(16 + result_action_map['1300068'][0]*0.05)
                        result_action_map['1300068'][0] = max(42,result_action_map['1300068'][0]-10)



    add_T = 0
    mark1 = 0
    mark2 = 0
    mark3 = 0
    mark4 = 0
    mark5 = 0
    mark6 = 0
    for g in online_data_map:
        try:
            if g in road_map:
                # print("G===========:",g)
                onlin = sorted(online_data_map[g].keys())
                Last_time=0
                for i in onlin:
                    Cid = road_map[g][0]
                    Cid1 = road_map[g][2]
                    # print(i,online_data_map[g][i][0])
                    if Last_time ==0:
                        Last_time = i
                    try:
                        if Cid != '0' and (Cid in se_map):
                            if road_map[g][1] == 'L' or road_map[g][1] == 'R':
                                se_map[Cid]['LR'][0] = (se_map[Cid]['LR'][0]+online_data_map[g][i][0]['nostop_speed'])/2
                                se_map[Cid]['LR'][1] = (se_map[Cid]['LR'][1]+online_data_map[g][i][0]['speed'])/2
                            if road_map[g][1] == 'U' or road_map[g][1] == 'D':
                                se_map[Cid]['NS'][0] = (se_map[Cid]['NS'][0]+online_data_map[g][i][0]['nostop_speed'])/2
                                se_map[Cid]['NS'][1] = (se_map[Cid]['NS'][1]+ online_data_map[g][i][0]['speed'])/2
                        if Cid1 != '0' and (Cid1 in se_map):
                            if road_map[g][3] == 'L' or road_map[g][3] == 'R':
                                se_map[Cid1]['LR'][0] = (se_map[Cid1]['LR'][0]+online_data_map[g][i][0]['nostop_speed'])/2
                                se_map[Cid1]['LR'][1] = (se_map[Cid1]['LR'][1]+ online_data_map[g][i][0]['speed'])/2
                            if road_map[g][3] == 'U' or road_map[g][3] == 'D':
                                se_map[Cid1]['NS'][0] = (se_map[Cid1]['NS'][0]+online_data_map[g][i][0]['nostop_speed'])/2
                                se_map[Cid1]['NS'][1] = (se_map[Cid1]['NS'][1]+online_data_map[g][i][0]['speed'])/2
                        if online_data_map[g][i][0]['jam_state_no'] > 0:
                            # print(i, online_data_map[g][i][0]['jam_state_no'])
                            se_map[road_map[g][0]][road_map[g][1]][0] += int((i - Last_time) * (online_data_map[g][i][0]['jam_state_no'] / 2))
                            if road_map[g][2] != '0':
                                se_map[road_map[g][2]][road_map[g][3]][0] += int(
                                    (i - Last_time) * (online_data_map[g][i][0]['jam_state_no'] / 2))
                        else:
                            se_map[road_map[g][0]][road_map[g][1]][0] = 0
                            se_map[road_map[g][2]][road_map[g][3]][0] = 0
                    except:
                        continue
                        # print("CrossId")
                    Last_time = i
        except:
            continue
    if se_map['1300047']["R"][0]>0:
        mark3=1
    Term_LX = result_action_map["1300069"]
    Term_LXD = result_action_map["1300068"]
    Term_FZX = result_action_map["1300101"]
    Term_ZJB = result_action_map["1300097"]
    Term_DLS = result_action_map["1300044"]
    Term_SDK = result_action_map["1300047"]
    Term_zjm = result_action_map["1300046"]
    Term_zn  = result_action_map["1300042"]
    Term_JD =  result_action_map["1300103"]
    Term_JDD = result_action_map["1300092"]
    Term_ZJD = result_action_map["1300106"]
    Term_SDKB = result_action_map["2703062"]
    Term_LXDN = result_action_map["2712127"]
    Term_XYQ = result_action_map["1300782"]
    if se_map["2703062"]["D"][0]>60:
        Term_SDKB[0]+=min(max(5,int(se_map["2703062"]["D"][0]/60)),15)
    if se_map["2703062"]["U"][0]>60:
        Term_SDKB[2] += min(max(5, int(se_map["2703062"]["U"][0] / 60)), 15)
    if se_map["2703062"]["L"][0]>60:
        Term_SDKB[1] += min(max(2, int(se_map["2703062"]["U"][0] / 60)), 5)
    if se_map["1300047"]["D"][0]>60:
        Term_SDKB[0] += min(max(5, int(se_map["1300047"]["D"][0] / 60)), 7)
    if se_map["1300069"]["U"][0]>60 or se_map["1300069"]["D"][0]>60:
        Term_LX[0]+=2
        Term_LX[1]+=2
    if se_map["1300069"]["L"][0]>60 or se_map["1300069"]["R"][0]>60:
        Term_LX[2]+=2
        Term_LX[3]+=1
    if se_map["1300101"]["U"][0]>60 or se_map["1300101"]["D"][0]>60:
        Term_FZX[1]+=min(max(max(se_map["1300101"]["U"][0],se_map["1300101"]["D"][0])/60,3),10)
        Term_FZX[2]+=1
    if se_map["1300044"]["U"][0]>60 or se_map["1300044"]["D"][0]>60:
        Term_DLS[1]+=min(max(max(se_map["1300044"]["U"][0],se_map["1300044"]["D"][0])/60,3),6)
        Term_DLS[2]+=2
    if se_map["1300044"]["L"][0]>60 or se_map["1300044"]["R"][0]>60:
        Term_DLS[0]+=3
    if se_map["1300103"]["D"][0]>60:
        Term_JD[0]+=4
        Term_JD[1]+=1
        Term_JDD[0]+=2
        Term_JDD[1]+=1
    if se_map["1300046"]["R"][0]>60:
        Term_zjm[0]+=3
    Term_ZJD[0] = int(Term_SDKB[0])
    Term_ZJD[1] = int(Term_SDKB[1]+7)
    Term_ZJD[2] = int(Term_SDKB[2]-7)
    ZJD,SDKB = get_min_sub(coordinate_map_set["1300106"]['s1'], coordinate_map_set["1300106"]['s2'], coordinate_map_set["2703062"]['s1'],
                coordinate_map_set["2703062"]['s2'])
    print("ZJDSDK",ZJD,SDKB,abs(ZJD-SDKB))
    print("ZJD",Term_ZJD[0]+Term_ZJD[1]+Term_ZJD[2],Term_SDKB[0]+Term_SDKB[1]+Term_SDKB[2])
    if abs(ZJD - SDKB) < 30:
        if ZJD < SDKB:
            Term_ZJD[0] += int(min(7,(SDKB- ZJD)*0.7))
            Term_ZJD[1] += int(min(3,(SDKB- ZJD)*0.3))
        else:
            Term_SDKB[0] += int(min(5,ZJD- SDKB)/2)
            Term_SDKB[1] += int(min(5,ZJD- SDKB)/2)
    else:
        Term_ZJD[0] += 10
    print("ZJD",Term_ZJD[0]+Term_ZJD[1]+Term_ZJD[2],Term_SDKB[0]+Term_SDKB[1]+Term_SDKB[2])
    ALL_LX = 0
    ALL_LXD = 0
    ALL_FZX = 0
    ALL_ZJB = 0
    ALL_DLS = 0
    ALL_SDK = 0
    ALL_zjm = 0
    ALL_zn = 0
    ALL_JD = 0
    ALL_JDD = 0

    # if mark1==1:
    #     if mark2 == 1:
    #         add_T=5
    #     else:
    #         if Term_LXD[9]==0:
    #             Term_LXD[9]=1
    #             Term_LXD[3]=int(Term_LXD[2])
    #             Term_LXD[2]=int(Term_LXD[1])
    #             Term_LXD[1]=20
    if mark3 == 1:
        Term_SDK[9]=1
        Term_SDK[2]=int(Term_SDK[1])
        Term_SDK[1]=55+int((Term_SDK[0]-40)*0.5)
        Term_SDK[0]=int((Term_SDK[0]-40)*0.5)

    print("mark",mark1,mark2,mark3,mark4,mark5,mark6)
    # for i in result_action_map:
    #     print(result_action_map[i])
    for i in range(0, 5):
        ALL_LX += Term_LX[i]
    for i in range(0, 5):
        ALL_LXD += Term_LXD[i]
    for i in range(0, 5):
        ALL_FZX += Term_FZX[i]
    for i in range(0, 5):
        ALL_ZJB += Term_ZJB[i]
    for i in range(0, 5):
        ALL_DLS += Term_DLS[i]
    for i in range(0, 5):
        ALL_SDK +=Term_SDK[i]
    for i in range(0, 5):
        ALL_zjm += Term_zjm[i]
    for i in range(0, 5):
        ALL_zn += Term_zn[i]
    for i in range(0, 5):
        ALL_JD += Term_JD[i]
    for i in range(0, 5):
        ALL_JDD += Term_JDD[i]



    print("Term_zjm", ALL_SDK, Term_zjm[0] + Term_zjm[1] + Term_zjm[2], Term_zn[0] + Term_zn[1])
    print("1300047_42",coordinate_map_set["1300047"]['s1'], coordinate_map_set["1300047"]['s2'])
    print("1300046S",coordinate_map_set["1300046"]['s1'], coordinate_map_set["1300046"]['s2'])
    print("1300042S",coordinate_map_set["1300042"]['s1'], coordinate_map_set["1300042"]['s2'])
    SDK_L1,zjm = get_min_sub(coordinate_map_set["1300047"]['s1'], coordinate_map_set["1300047"]['s2'],
                coordinate_map_set["1300046"]['s1'], coordinate_map_set["1300046"]['s2'])

    print("Term_zjm", ALL_SDK, Term_zjm[0] + Term_zjm[1] + Term_zjm[2], Term_zn[0] + Term_zn[1])
    if ALL_SDK> ALL_zjm:
        Term_zjm[0] += int((ALL_SDK - ALL_zjm) * 0.8)
        Term_zjm[1] += int((ALL_SDK - ALL_zjm) * 0.1)
        Term_zjm[2] += int((ALL_SDK - ALL_zjm) * 0.1)

        if abs(SDK_L1 - zjm) < 50:
            if SDK_L1 > zjm:
                Term_zjm[0] += min(10, SDK_L1 - zjm)
            else:
                Term_zjm[0] -= min(4, zjm - SDK_L1)
        else:
            Term_zjm[0] += 10
    ALL_zjm = Term_zjm[0] + Term_zjm[1] + Term_zjm[2]
    if ALL_zjm > ALL_zn:
        Term_zn[0] += int((ALL_zjm - ALL_zn) * 0.7)
        Term_zn[1] += int((ALL_zjm - ALL_zn) * 0.3)
    zjm1,zn = get_min_sub( coordinate_map_set["1300046"]['s1'], coordinate_map_set["1300046"]['s2'],
                coordinate_map_set["1300042"]['s1'], coordinate_map_set["1300042"]['s2'])
    print("zjm_zn",zjm1,zn,abs(zjm1-zn))
    if abs(zjm1 - zn) < 50:
        if zjm1 > zn:
            Term_zn[0] += min(10, zjm1 - zn)
        else:
            Term_zn[0] -= min(4, zn - zjm1)
    else:
        Term_zn[0] += 10
    print("SDK_L1",SDK_L1,zjm,abs(SDK_L1-zjm))
    print("Term_zjm",ALL_SDK,Term_zjm[0]+Term_zjm[1]+Term_zjm[2],Term_zn[0]+Term_zn[1])
    print("###############")


    FZB = (Term_FZX[0]+Term_FZX[1]+Term_FZX[2]-Term_ZJB[0]-Term_ZJB[1])
    Term_ZJB[0] += int(FZB*0.6)
    Term_ZJB[1] += int(FZB*0.4)

    FZX,ZJB = get_min_sub(coordinate_map_set["1300101"]['s1'], coordinate_map_set["1300101"]['s2'],
                           coordinate_map_set["1300097"]['s1'], coordinate_map_set["1300097"]['s2'])
    if abs(FZX-ZJB) < 50:
        if FZX>ZJB:
            Term_FZX[1] -= int(min(2,(FZX-ZJB)/2))
            Term_ZJB[0] += int(min(8,(FZX-ZJB)/2))
        else:
            Term_FZX[0] += int(min(8, (ZJB-FZX) / 2))
            Term_ZJB[0] -= int(min(2, (ZJB-FZX) / 2))
    else:
        Term_FZX[1]+=5
        Term_FZX[0]+=5
    print(ZJB,FZX)
    print("ZJB,FZX",Term_ZJB[0]+Term_ZJB[1]+Term_ZJB[2],Term_FZX[0]+Term_FZX[1]+Term_FZX[2])
    ALL_LXD = Term_LXD[0]+Term_LXD[1]+Term_LXD[2]+Term_LXD[3]
    ALL_LXDN = Term_LXDN[0]+Term_LXDN[1]
    Term_LXDN[1]+=int((ALL_LXD-ALL_LXDN)*0.8)
    Term_LXDN[0]+=int((ALL_LXD-ALL_LXDN)*0.2)
    LXD3,LXDN = get_min_sub(coordinate_map_set["1300068"]['s1'], coordinate_map_set["1300068"]['s2'],
                           coordinate_map_set["2712127"]['s1'], coordinate_map_set["2712127"]['s2'])
    print("27127",coordinate_map_set["1300068"]['s1'], coordinate_map_set["1300068"]['s2'],
                           coordinate_map_set["2712127"]['s1'], coordinate_map_set["2712127"]['s2'])
    if abs(LXD3-LXDN)<50:
        if LXD3 > LXDN:
            Term_LXDN[1] += min(10, LXD3 - LXDN)
        else:
            Term_LXDN[1] -= min(10, LXDN-LXD3)
    else:
        Term_LXDN[1] += 10
    Term_vit_road = result_action_map['2719089']

    for i in range(0,10):
        Term_vit_road[i] = Term_LXD[i]

    # 4、白石桥(1300094)需增加模型南北阶段时间(对应阶段号0 #UD)
    if "1300094" in result_action_map:
        result_action_map["1300094"][3] += 10
        result_action_map["1300094"][2] += 10 # UD
    # 5、北太平桥(1300067)需增加模型南北左转阶段时间(对应阶段号2#UDL)
    if "1300067" in result_action_map:
        result_action_map["1300067"][2] += 15 # UDL
    # 6、志新桥(1300409)加东西左转时间(对应阶段号1 #LRL)
    if "1300409" in result_action_map:
        result_action_map["1300409"][1] += 5 # LRL
    # 7、交通大学路东口(1300092)，南北方向在早晚高峰（7-9点，17-19点）加时间，其他时间减时间，加减的量在7_15s之间浮动(对应阶段号0#UD)
    if "1300092" in result_action_map:
        base_time = result_action_map["1300092"][0] # UD
        # 根据计算的基础时间(24-40秒之间)进行线性映射，计算7-15秒的浮动增量
        # 流量越大(基础时间越长)，增加/减少的浮动值越大
        offset = 7 + (base_time - 24) * (15 - 7) / (40 - 24)
        offset = int(max(7, min(15, offset)))
        if (7 <= hour <= 9) or (17 <= hour <= 19):
            result_action_map["1300092"][0] += offset # UD 早晚高峰加时间
        else:
            result_action_map["1300092"][0] -= offset # UD 其他时间减时间


    for id in [1300974,1300323,1300271,1300318]:
        road_idd=str(id)
        schedule = get_time_map(int(id))
        current_time = int(time.time() * 1000)
        t = time.localtime(current_time / 1000)

        time_zong1= schedule[str(t.tm_hour)]
        sum_time_z1 = sum(time_zong1) - time_zong1[9]
        time_zong2 = sum(result_action_map[road_idd]) - result_action_map[road_idd][9]
        if time_zong2!=0:
            for i in range(8):
                result_action_map[road_idd][i] = round((result_action_map[road_idd][i]/time_zong2)*sum(time_zong1))

            if (sum(result_action_map[road_idd]) - result_action_map[road_idd][9] != sum_time_z1):
                sum11=sum_time_z1 - (sum(result_action_map[road_idd]) - result_action_map[road_idd][9])
                chang=0

                for i in range(9):
                    if result_action_map[road_idd][i]!=0:
                        chang+=1
                    else:
                        break

                if sum11>0:
                    for i in range(chang):
                        result_action_map[road_idd][i]+=sum11//chang

                    result_action_map[road_idd][0]+=sum11%chang
                else:
                    sum11=abs(sum11)
                    for i in range(chang):
                        result_action_map[road_idd][i]-=sum11//chang

                    result_action_map[road_idd][0]-=sum11%chang


                # result_action_map[road_idd][0] += sum_time_z1 - (sum(result_action_map[road_idd])-result_action_map[road_idd][9])
    if (0 <= int(t.tm_hour) <= 6 or 10 <= int(t.tm_hour) <= 16 or 20<= int(t.tm_hour) <=23 ):
        road_idd = str(1300318)
        schedule = get_time_map(int(id))
        current_time = int(time.time() * 1000)
        t = time.localtime(current_time / 1000)
        result_action_map["1300318"] = schedule[str(t.tm_hour)]

    return result_action_map
