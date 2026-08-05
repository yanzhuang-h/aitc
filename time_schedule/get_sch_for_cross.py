import json
import time

from lib.AITC_tool import Get_Fine_map
road_info_path = 'lib/road_info.json'

def get_sch(F,road_info,Cross_id,h):
    ret = [0,0,0,0,0,0,0,0,0,0]
    L = F[0]
    R = F[1]
    U = F[2]
    D = F[3]
    sub = [R - L, L - R, D - U, U - D]
    M = 0
    state = "0"
    local = '0'
    for i in range(0, 4):
        if str(i + 1) not in road_info[Cross_id]:
            sub[i] = 0
        if sub[i] > M:
            local = str(i + 1)
            M = max(sub[i], M)
            print("not_have", i + 1,L,R,U,D)
    try:
        if M > 15:
            state = local
        # print(state)
        if state == "0" and '5' in road_info[Cross_id] and h<=5:
            state = '5'
        if state !='0':
            print(Cross_id,h)
        ret= road_info[Cross_id][state]['min_pass_time'].copy()
        # print(road_info[Cross_id][state]['phase'])
        markL = -1
        markR = -1
        markLR = -1
        markUD = -1
        markU = -1
        markD = -1
        for phase in range(0, 8):
            if road_info[Cross_id][state]['phase'][phase] == 'UD':
                markUD = phase
            if road_info[Cross_id][state]['phase'][phase] == 'LR':
                markLR = phase
            if road_info[Cross_id][state]['phase'][phase] == 'L':
                markL = phase
            if road_info[Cross_id][state]['phase'][phase] == 'R':
                markR = phase
            if road_info[Cross_id][state]['phase'][phase] == 'U':
                markU = phase
            if road_info[Cross_id][state]['phase'][phase] == 'D':
                markD = phase
        for phase in range(0, 8):
            # print(road_info[Cross_id][state]['phase'][phase])
            if road_info[Cross_id][state]['phase'][phase] == 'UD':
                add = 0
                if markD == -1:
                    add += max(D - U, 0)
                if markU == -1:
                    add += max(U - D, 0)
                ret[phase] += min(U, D) + add
            if road_info[Cross_id][state]['phase'][phase] == 'UD2':
                add = 0
                if markD == -1:
                    add += max(D - U, 0)
                if markU == -1:
                    add += max(U - D, 0)
                ret[phase] += int((min(U, D) + add) / 2)
            if road_info[Cross_id][state]['phase'][phase] == 'LR2':
                add = 0
                if markL == -1:
                    add += max(L - R, 0)
                if markR == -1:
                    add += max(R - L, 0)

                ret[phase] += int((min(L, R) + add) / 2)
            if road_info[Cross_id][state]['phase'][phase] == 'LR':
                add = 0
                if markL == -1:
                    add += max(L - R, 0)
                if markR == -1:
                    add += max(R - L, 0)

                ret[phase] += min(L, R) + add

            if road_info[Cross_id][state]['phase'][phase] == 'LRL':
                ret[phase]+= max(L, R) * 0.3 * road_info[Cross_id][state]['phase_weight'][
                    phase]
            if road_info[Cross_id][state]['phase'][phase] == 'LRL2':
                ret[phase] += max(L, R) * 0.15 * road_info[Cross_id][state]['phase_weight'][
                    phase]
            if road_info[Cross_id][state]['phase'][phase] == 'UDL':
                ret[phase]+= max(U, D) * 0.3 * road_info[Cross_id][state]['phase_weight'][
                    phase]
            if road_info[Cross_id][state]['phase'][phase] == 'UDL2':
                ret[phase] += max(U, D) * 0.15 * road_info[Cross_id][state]['phase_weight'][
                    phase]

            if road_info[Cross_id][state]['phase'][phase] == 'L':
                if markLR == -1:
                    ret[phase] += L
                else:
                    ret[phase] = max(L - R, 15)
            if road_info[Cross_id][state]['phase'][phase] == 'R':
                if markLR == -1:
                    ret[phase] += R
                else:
                    ret[phase]= max(R - L, 15)

            if road_info[Cross_id][state]['phase'][phase] == 'U':
                if markUD == -1:
                    ret[phase] += U
                else:

                    ret[phase] = max(U - D, 15)
            if road_info[Cross_id][state]['phase'][phase] == 'D':
                if markUD == -1:
                    ret[phase] += D
                else:
                    ret[phase] = max(D - U, 15)
            # print("hava")
        ret[9] = int(state)
        # print(Cross_id, L, R, U, D, markLR, markUD, state)
        # print(Cross_id, ret)
        return ret
    except:
        print("error_cross", Cross_id,state)

def get_sch_for_cross(cross_id,flow_path,stage_path,online_path,radar_path,time_schedule,extend_path):
    try:
        FINE = Get_Fine_map()
        with open(road_info_path, 'r', encoding='utf-8') as f:
            road_info = json.load(f)
        if cross_id in FINE:
            for i in range(0,24):
                H = str(i)
                F = FINE[cross_id][H]
                ret = get_sch(F,road_info,cross_id,i)
                # print(cross_id,H,ret)

                time_schedule[H] = ret.copy()


    except:
        print("erro",cross_id)

    print(cross_id,time_schedule)
    return  time_schedule

def Get_add(pass_state):
    add = 0
    mark =0
    if pass_state[0]!=0:
        mark=1
        addT = int((pass_state[1]/pass_state[0])*6)
        add = int((pass_state[1]/pass_state[0])*4)
        if addT==0 and pass_state[2]>22:
            add-=1
    return add,mark
def update_FIne_turn_for_cross(cross_id,flow_path,stage_path,online_path,radar_path,Fine_turn,extend_path):
    # print(Fine_turn)
    online_data = get_online_map(online_path)
    cross_id = int(cross_id)
    state = get_Cross_id_online_state(online_data,cross_id)
    for i in state:
        hour = str(i)
        Ladd,Lmark = Get_add(state[i]['L'])
        if Lmark!=0:
            Fine_turn[hour][0]= max(Fine_turn[hour][0]+Ladd,0)
        Radd,Rmark = Get_add(state[i]['R'])
        if Rmark!=0:
            Fine_turn[hour][1]= max(Fine_turn[hour][1]+Radd,0)
        Uadd,Umark = Get_add(state[i]['U'])
        if Umark!=0:
            Fine_turn[hour][2]= max(Fine_turn[hour][2]+Uadd,0)
        Dadd,Dmark = Get_add(state[i]['D'])
        if Dmark!=0:
            Fine_turn[hour][3]= max(Fine_turn[hour][3]+Dadd,0)
    return Fine_turn



def get_online_map(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        online = f.readlines()
    online_map = dict()
    for line in online:
        try:
            data = json.loads(line)
            ti = data["time"]
            if ti not in online_map:
                online_map[ti] = dict()
            online_map[ti][data['rid']] = data
        except:
            continue
    return online_map



def get_Cross_id_online_state(Online_data,cross_id):
    time_scatter = dict()
    for i in range(0,24):
        hour = i
        time_scatter[hour] = {'L': [0, 0, 20, 0, 0], 'R': [0, 0, 20, 0, 0],'U': [0, 0, 20, 0, 0],'D': [0, 0, 20, 0, 0]}
        # print("aaa")
    try:
        for i in Online_data:
            hour = time.localtime(i).tm_hour
            for rid in Online_data[i]:
                if rid in online_map:
                    if cross_id in online_map[rid]:
                        Turn = online_map[rid][cross_id]
                        data = Online_data[i][rid]
                        if Turn in time_scatter[hour]:
                            TS = data['speed'] / data['max_speed']
                            TNS = data['nostop_speed'] / data['max_speed']
                            if data['jam_state_no']!=0 or TNS<0.2 or (TS <0.15 and TNS<0.3) or data["avg_delay_dur"]>150:
                                time_scatter[hour][Turn][1] += 1
                            time_scatter[hour][Turn][2] = (time_scatter[hour][Turn][2]+data['speed'])/2
                            time_scatter[hour][Turn][0] += 1
    except:
        print("erro")
    return time_scatter



online_map ={
'13FK10C5QR013FK10C5OP00': {1300194: 'U', 1300228: 'NU'} ,
'13FK10C5OP013FK10C5QR00': {1300194: 'ND', 1300228: 'D'} ,
'13FK10C5OP013FII0C5OP00': {1300194: 'L'} ,
'13FM60C5OP013FK10C5OP00': {1300194: 'R'} ,
'13GBT0C655013GB00C65400': {1100308: 'R'} ,
'13GB00C654013G9U0C65200': {1100308: 'NR'} ,
'13G9U0C652013GB00C65400': {1100308: 'L'} ,
'13GB00C654013GBT0C65500': {1100308: 'NL'} ,
'13GB60C64Q013GB00C65400': {1100308: 'D'} ,
'13GAT0C66S013GAR0C68B00': {1300099: 'D'} ,
'13GAR0C68B013GAQ0C69300': {1300099: 'ND', 1300100: 'D'} ,
'13GAQ0C693013GAR0C68B00': {1300099: 'U', 1300100: 'NU'} ,
'13GAR0C68B013GAT0C66S00': {1300099: 'NU'} ,
'13FT50C63O013FT20C64S00': {1300105: 'D', 2704064: 'U'} ,
'13FT20C64S013FT40C65C00': {1300105: 'U', 1300054: 'D2'} ,
'13FT20C64S013FRV0C64P00': {1300105: 'L'} ,
'13G0P0C5L8013G0Q0C5KT00': {1300110: 'U'} ,
'13G0Q0C5KT013G0R0C5JR00': {1300110: 'NU'} ,
'13G0R0C5KG013G0Q0C5KT00': {1300110: 'D'} ,
'13G0Q0C5KT013G0Q0C5L800': {1300110: 'ND', 1300109: 'D1'} ,
'13G0Q0C5KT013G090C5KS00': {1300110: 'L', 1300095: 'R'} ,
'13G1P0C5KT013G0Q0C5KT00': {1300110: 'R'} ,
'13FSV0C5LS013FSV0C5KT00': {1300117: 'U'} ,
'13FUC0C5KS013FSV0C5KT00': {1300117: 'R', 1300116: 'L'} ,
'13FSV0C5KT013FT00C5JS00': {1300117: 'D'} ,
'13FP00C65F013FOU0C66900': {1300164: 'U'} ,
'13FP00C65F013FNH0C65800': {1300164: 'L'} ,
'13FQM0C65I013FP00C65F00': {1300164: 'R'} ,
'13FP10C653013FP00C65F00': {1300164: 'D'} ,
'13FIT0C65R013FIT0C66K00': {1300303: 'U'} ,
'13FIT0C65R013FHR0C65N00': {1300303: 'L'} ,
'13FK40C65Q013FIT0C65R00': {1300303: 'R', 2704102: 'NR'} ,
'13FIT0C65R013FK40C65Q00': {1300303: 'NL', 2704102: 'L'} ,
'13FIU0C653013FIT0C65R00': {1300303: 'D'} ,
'13FOD0C5N2013FOD0C5L200': {1300310: 'U'} ,
'13FM70C5L2013FOD0C5L200': {1300310: 'L'} ,
'13FOD0C5L2013FOD0C5JS00': {1300310: 'D'} ,
'13FK40C669013FK40C65Q00': {2704102: 'U'} ,
'13FM30C65Q013FK40C65Q00': {2704102: 'R'} ,
'13FK40C65Q013FK40C65G00': {2704102: 'D'} ,
'13G090C5KS013G0A0C5KL00': {1300095: 'D', 1300096: 'U'} ,
'13G0A0C5KL013G040C5KL00': {1300096: 'L'} ,
'13FVB0C63V013FT50C63O00': {2704064: 'R'} ,
'13FT50C63O013FS90C63M00': {2704064: 'L'} ,
'13FT70C633013FT50C63O00': {2704064: 'D', 1300052: 'U'} ,
'13FIT0C60R113FIC0C60P00': {1300243: 'L', 1300183: 'R'} ,
'13FJB0C60S013FIT0C60R10': {1300243: 'R', 1300245: 'L'} ,
'13FJ00C60B013FIT0C60R10': {1300243: 'D', 1300370: 'U'} ,
'13FIC0C61K013FIC0C60P00': {1300183: 'U'} ,
'13FJB0C60S013FJ30C61O00': {1300245: 'U', 1300250: 'D'} ,
'13FK30C60U013FJB0C60S00': {1300245: 'R', 1300371: 'L'} ,
'13FK30C60A013FK40C5VK00': {1300246: 'U', 1300373: 'NU'} ,
'13FK40C5VK013FJ50C5VJ00': {1300246: 'NR', 1300369: 'R'} ,
'13FKK0C5VK013FK40C5VK00': {1300246: 'R'} ,
'13FJ50C5VJ013FK40C5VK00': {1300246: 'L', 1300369: 'NL'} ,
'13FK40C5VK013FK30C60A00': {1300246: 'ND', 1300373: 'D'} ,
'13FMF0C60A013FL00C60A00': {1300248: 'R'} ,
'13FL00C60A013FKU0C60A00': {1300248: 'L'} ,
'13FL00C60A013FL00C5VK00': {1300248: 'D', 1300247: 'U'} ,
'13FK30C60A013FJ00C60B00': {1300370: 'R', 1300373: 'L'} ,
'13FJ00C60B013FIT0C5V800': {1300370: 'L'} ,
'13FJ50C5VJ013FJ00C60B00': {1300370: 'D', 1300369: 'U'} ,
'13FM60C5LV013FM60C5N300': {1300200: 'D', 1300311: 'ND2', 1300312: 'ND'} ,
'13FM60C5NU013FM60C5N300': {1300200: 'U'} ,
'13FMR0C5N5013FM60C5N301': {1300200: 'R'} ,
'13FLG0C5N3013FM60C5N301': {1300200: 'L'} ,
'13FM60C5LH013FM60C5LV00': {1300200: 'D1', 1300311: 'ND1', 1300312: 'D', 1300313: 'ND'} ,
'13FK00C5N1013FLG0C5N301': {1300200: 'L1'} ,
'13FNR0C5N4013FMR0C5N501': {1300200: 'R1'} ,
'13FOE0C5N4013FNR0C5N401': {1300200: 'R2'} ,
'13FM60C5N3013FM60C5NU00': {1300200: 'ND'} ,
'13FM60C5N3013FLG0C5N301': {1300200: 'NR'} ,
'13FM60C5N3013FM60C5LV00': {1300200: 'NU', 1300311: 'U2', 1300312: 'U'} ,
'13FLG0C5N3013FL50C5N401': {1300200: 'NR1'} ,
'13FL50C5N4013FKU0C5N401': {1300200: 'NR2'} ,
'13FM60C5N3013FNI0C5N201': {1300200: 'NL'} ,
'13FNI0C5N2013FOD0C5N201': {1300200: 'NL1'} ,
'13FUC0C5N3013FUG0C5N600': {1300059: 'ND'} ,
'13FUD0C5MF013FUC0C5N300': {1300059: 'D', 1300116: 'ND2'} ,
'13FUD0C5O7013FUC0C5N300': {1300059: 'U'} ,
'13FUC0C5N3013FUB0C5MH00': {1300059: 'NU', 1300116: 'U3'} ,
'13G9T0C66S013G8T0C66T00': {1300086: 'R'} ,
'13G890C66T013G8T0C66T00': {1300086: 'L'} ,
'13G8T0C66T013G890C66T10': {1300086: 'NR'} ,
'13G8T0C66T013G9T0C66S00': {1300086: 'NL'} ,
'13G910C66A013G8T0C66T00': {1300086: 'D'} ,
'13G8T0C66T013G900C67K00': {1300086: 'ND'} ,
'13G8E0C67L013G8T0C66T00': {1300086: 'U'} ,
'13G8T0C66T013G8T0C66900': {1300086: 'NU'} ,
'13FK20C61T013FK20C63D00': {1300253: 'D'} ,
'13FK20C63D013FK10C64200': {1300253: 'ND'} ,
'13FK10C642013FK20C63D00': {1300253: 'U'} ,
'13FLE0C63M013FK20C63D00': {1300253: 'R'} ,
'13FML0C63G013FLE0C63M00': {1300253: 'R2'} ,
'13FNJ0C636013FML0C63G00': {1300253: 'R3'} ,
'13FK20C63D013FHV0C6390': {1300253: 'NR'} ,
'13FHV0C639013FFU0C63C00': {1300253: 'NR1', 1300252: 'NR'} ,
'13FIF0C637013FK20C63D01': {1300253: 'L', 1300252: 'NL1'} ,
'13FHV0C639013FIF0C63701': {1300253: 'L1', 1300252: 'NL'} ,
'13FHE0C637013FHV0C63900': {1300253: 'L2', 1300252: 'L'} ,
'13FGO0C639013FHE0C63700': {1300253: 'L3', 1300252: 'L1'} ,
'13FK20C63D013FL00C63I00': {1300253: 'NL'} ,
'13FL20C63I013FLM0C63K00': {1300253: 'NL1'} ,
'13FLM0C63K013FNI0C63200': {1300253: 'NL2'} ,
'13FM60C5HV013FM70C5JO00': {1300318: 'DF'} ,
'13FM60C5HV013FM60C5JQ00': {1300318: 'D'} ,
'13FM60C5JQ013FM60C5KR00': {1300318: 'ND', 1300311: 'D'} ,
'13FM60C5KR013FM60C5JQ00': {1300318: 'U', 1300311: 'NU'} ,
'13FM60C5JQ013FM60C5HV00': {1300318: 'NU'} ,
'13G2B0C6BT013G2A0C6CL00': {1300358: 'D'} ,
'13G2C0C6AR013G2B0C6BT00': {1300358: 'D1'} ,
'13G2E0C69R013G2C0C6AR00': {1300358: 'D2'} ,
'13G2A0C6CL013G290C6CU00': {1300358: 'ND'} ,
'13G290C6CV013G280C6D600': {1300358: 'ND1'} ,
'13G270C6D6013G2A0C6CL00': {1300358: 'U'} ,
'13G260C6E3013G270C6D600': {1300358: 'U1'} ,
'13G2A0C6CL013G290C6BK00': {1300358: 'NU'} ,
'13G290C6BK013G2A0C6B400': {1300358: 'NU1'} ,
'13G2A0C6B4013G2E0C69R00': {1300358: 'NU2'} ,
'13G2B0C6BT013G2A0C6CL01': {1300358: 'DF'} ,
'13G1O0C6CK013G2A0C6CL00': {1300358: 'L'} ,
'13G170C6CJ013G1O0C6CK00': {1300358: 'L1'} ,
'13G060C6CI013G170C6CJ00': {1300358: 'L2'} ,
'13FVK0C6CI013G060C6CI00': {1300358: 'L3'} ,
'13G2A0C6CL013G2O0C6CL00': {1300358: 'NL', 1300357: 'L'} ,
'13G2O0C6CL013G350C6CK00': {1300358: 'NL1', 1300357: 'NL'} ,
'13G350C6CK013G3J0C6CK00': {1300358: 'NL2', 1300357: 'NL1'} ,
'13G2O0C6CL013G2A0C6CL00': {1300358: 'R', 1300357: 'NR'} ,
'13G350C6CL013G2O0C6CL00': {1300358: 'R1'} ,
'13G3K0C6CL013G350C6CL00': {1300358: 'R2', 1300357: 'R2'} ,
'13G5B0C6CL013G3K0C6CL00': {1300358: 'R3'} ,
'13G2A0C6CL013G1A0C6CL00': {1300358: 'NR'} ,
'13G1A0C6CL013G0V0C6CK00': {1300358: 'NR1'} ,
'13G1O0C6CK013G2A0C6CL01': {1300358: 'LF'} ,
'13G2A0C6CL013G2O0C6CL01': {1300358: 'NLF', 1300357: 'LF'} ,
'13FT50C65P013FT40C66H00': {1300054: 'D'} ,
'13FT40C65C013FT50C65P00': {1300054: 'D1'} ,
'13FT40C66H013FQJ0C66H00': {1300054: 'L'} ,
'13FV10C66G013FT40C66H00': {1300054: 'R'} ,
'13G7U0C62B013G7E0C62J00': {1300104: 'R'} ,
'13G7T0C621013G7Q0C62H00': {1300104: 'RF1'} ,
'13G7Q0C62H013G7E0C62J00': {1300104: 'RF'} ,
'13G7E0C62J013G6J0C62Q10': {1300104: 'NR'} ,
'13G7E0C62J013G6J0C62T00': {1300104: 'NR1'} ,
'13G6I0C62Q013G7E0C62J00': {1300104: 'L'} ,
'13G6J0C62Q013G700C62M00': {1300104: 'L1'} ,
'13G7B0C62S013G7E0C62J00': {1300104: 'U'} ,
'13G7E0C62J013G7B0C62S00': {1300104: 'ND'} ,
'13G7B0C62S013G6T0C64E00': {1300104: 'ND1'} ,
'13G0P0C5LI013G0P0C5L800': {1300109: 'NU'} ,
'13G0P0C5LT013G0P0C5LI00': {1300109: 'U'} ,
'13G0P0C5M6013G0P0C5LT00': {1300109: 'U1'} ,
'13G0P0C5MA013G0P0C5M600': {1300109: 'U2'} ,
'13G0P0C5MR013G0P0C5MA00': {1300109: 'U3'} ,
'13G0Q0C5L8013G0P0C5LI00': {1300109: 'D'} ,
'13G0P0C5LI013G0P0C5LT00': {1300109: 'ND'} ,
'13G0P0C5LT013G0Q0C5M600': {1300109: 'ND1'} ,
'13G0P0C5LI013G0S0C5LI00': {1300109: 'R'} ,
'13G0S0C5LI013G2G0C5LJ00': {1300109: 'R1'} ,
'13FK10C5QR013FII0C5QT00': {1300228: 'L', 1300361: 'R'} ,
'13FKB0C5QR013FK10C5QR00': {1300228: 'R'} ,
'13FME0C5QH013FKB0C5QR00': {1300228: 'R1'} ,
'13G2I0C5RU013G1I0C5S100': {1100257: 'R'} ,
'13G1H0C5RV013G200C5RU01': {1100257: 'L'} ,
'13G200C5RU013G2I0C5RU01': {1100257: 'NL'} ,
'13G4I0C63M013G4Q0C63O00': {1300090: 'L', 1300091: 'NL'} ,
'13G4Q0C63O013G4I0C63M00': {1300090: 'NR', 1300091: 'R'} ,
'13G4Q0C63O013G4P0C63T00': {1300090: 'U'} ,
'13G4U0C63G013G4Q0C63O00': {1300090: 'D'} ,
'13G4Q0C63O013G5Q0C64300': {1300090: 'NL'} ,
'13G5Q0C643013G6T0C64E00': {1300090: 'NL1'} ,
'13G5Q0C643013G4Q0C63O00': {1300090: 'R'} ,
'13G6T0C64E013G5Q0C64300': {1300090: 'R1'} ,
'13G3K0C63J013G4I0C63M00': {1300091: 'L'} ,
'13G490C63R013G4I0C63M01': {1300091: 'U'} ,
'13G4I0C63M013G5B0C63710': {1300091: 'D'} ,
'13G300C653013G1S0C65100': {1300102: 'L'} ,
'13G1S0C651013FV90C64S00': {1300102: 'L1', 1301046: 'R'} ,
'13G2T0C65G013G300C65300': {1300102: 'U'} ,
'13G2O0C66O013G2T0C65G00': {1300102: 'U1'} ,
'13G300C653013G3F0C64A00': {1300102: 'NU'} ,
'13G3F0C64A013G490C63R00': {1300102: 'NU1'} ,
'13G3B0C64H013G300C65300': {1300102: 'D'} ,
'13G300C653013G2O0C66O00': {1300102: 'ND'} ,
'13FVA0C64K013FV90C64S00': {1301046: 'D'} ,
'13FVE0C639013FVA0C64K00': {1301046: 'D1'} ,
'13FV90C64S013FV10C66G00': {1301046: 'ND'} ,
'13FV40C65H013FV90C64S00': {1301046: 'U'} ,
'13FV30C65P013FV40C65H00': {1301046: 'U1'} ,
'13FV10C66G013FV20C66100': {1301046: 'U2'} ,
'13FV90C64S013FVB0C63V00': {1301046: 'NU'} ,
'13FVB0C63V013FVE0C63900': {1301046: 'NU1'} ,
'13FK60C5T9013FK30C5SH00': {1300241: 'D'} ,
'13FK60C5U9013FK60C5T900': {1300241: 'U'} ,
'13FL00C5T8013FK60C5T900': {1300241: 'R'} ,
'13FK60C5T9013FJK0C5TB10': {1300241: 'NR'} ,
'13FJK0C5TB013FK60C5T900': {1300241: 'L'} ,
'13FJ10C5TE013FJK0C5TB00': {1300241: 'L1'} ,
'13FK60C5T9013FL00C5T800': {1300241: 'NL'} ,
'13FFU0C63C013FGO0C63900': {1300252: 'L2'} ,
'13FK20C63D013FHV0C63901': {1300252: 'R'} ,
'13FI00C634013FHV0C63900': {1300252: 'D'} ,
'13FM60C5KR013FM60C5LH00': {1300311: 'ND', 1300313: 'D'} ,
'13FM60C5LH013FM60C5KR00': {1300311: 'U', 1300313: 'NU'} ,
'13FM60C5LV013FM60C5LH00': {1300311: 'U1', 1300312: 'NU', 1300313: 'U'} ,
'13FM60C5KR013FK00C5KQ00': {1300311: 'L', 1300314: 'R'} ,
'13FK00C5KQ013FII0C5KQ00': {1300314: 'L'} ,
'13FII0C5QT013FFV0C5QV00': {1300361: 'L'} ,
'13FII0C5Q9013FII0C5QT00': {1300361: 'D'} ,
'13FII0C5QT013FII0C5R100': {1300361: 'ND'} ,
'13FII0C5R1013FII0C5QT00': {1300361: 'U'} ,
'13FII0C5QT013FII0C5Q900': {1300361: 'NU'} ,
'13FIT0C5RR013FII0C5R100': {1300361: 'U1', 1300366: 'D'} ,
'13FOG0C5VB013FOT0C60200': {2703916: 'D'} ,
'13FOT0C602013FOG0C5VB00': {2703916: 'NU'} ,
'13FQR0C603013FOT0C60200': {2703916: 'R'} ,
'13FOT0C602013FP40C60F00': {2703916: 'ND'} ,
'13FP40C60F013FP80C60Q00': {2703916: 'ND1'} ,
'13FP40C60F013FOT0C60200': {2703916: 'U'} ,
'13FP80C60Q013FP40C60F00': {2703916: 'U1'} ,
'13FUC0C5TH013FTU0C5TH00': {1300037: 'L', 1300038: 'R'} ,
'13FUT0C5TH013FUC0C5TH00': {1300037: 'R'} ,
'13FVQ0C5TH013FUV0C5TH00': {1300037: 'R1'} ,
'13FUC0C5TC013FUC0C5TH00': {1300037: 'D'} ,
'13FUE0C5S4013FUC0C5TC00': {1300037: 'D1'} ,
'13FTU0C5TS013FTU0C5TH00': {1300038: 'U'} ,
'13FTU0C5TH013FSU0C5TH00': {1300038: 'L'} ,
'13FVE0C639013FT70C63300': {1300052: 'R'} ,
'13FT70C633013FRR0C63000': {1300052: 'L'} ,
'13FRR0C630013FRN0C62V00': {1300052: 'L1'} ,
'13FRN0C62V013FQV0C62V00': {1300052: 'L2'} ,
'13GAQ0C693013GAP0C69R00': {1300100: 'ND'} ,
'13GAP0C69R013GAQ0C69300': {1300100: 'U'} ,
'13G280C5O5013G0O0C5O500': {1300112: 'R', 1300063: 'L'} ,
'13G0P0C5NI013G0O0C5O500': {1300112: 'D'} ,
'13G0P0C5N4013G0P0C5NI00': {1300112: 'D1'} ,
'13G0O0C5O5013G030C5O600': {1300112: 'L'} ,
'13G0O0C5O5013G0M0C5O900': {1300112: 'U'} ,
'13GGM0C6EE013GGE0C6EE00': {1400174: 'R'} ,
'13GGE0C6EE013GFE0C6EE00': {1400174: 'NR'} ,
'13GFF0C6ED013GGE0C6EE00': {1400174: 'L'} ,
'13GGE0C6EE013GGM0C6EE00': {1400174: 'NL'} ,
'13GGH0C6DR013GGE0C6EE00': {1400174: 'D'} ,
'13FKK0C5VK013FJ50C5VJ00': {1300247: 'L'} ,
'13FHM0C61J013FHK0C61J00': {1300251: 'R'} ,
'13FIA0C61K013FHM0C61J00': {1300251: 'R1'} ,
'13FHK0C61J013FHF0C63500': {1300251: 'U'} ,
'13FHF0C635013FHE0C63700': {1300251: 'U1'} ,
'13FHK0C61J013FGS0C61K00': {1300251: 'L'} ,
'13FGS0C61K013FFP0C61K00': {1300251: 'L1'} ,
'13G0G0C6DI013G0B0C6E100': {1300264: 'D'} ,
'13G0B0C6E1013G0G0C6DI00': {1300264: 'D1'} ,
'13G0G0C6DI013G0G0C6DE00': {1300264: 'D2'} ,
'13G0B0C6E1013FVH0C6E300': {1300264: 'L'} ,
'13G140C6E2013G0B0C6E100': {1300264: 'R'} ,
'13G260C6E3013G140C6E200': {1300264: 'R1'} ,
'13G0B0C6E1013G0A0C6EE00': {1300264: 'ND'} ,
'13G0A0C6EI013G090C6ET00': {1300264: 'ND1'} ,
'13G090C6ET013G080C6FH00': {1300264: 'ND2'} ,
'13G0A0C6EE013G0B0C6E100': {1300264: 'U'} ,
'13G0A0C6EI013G0A0C6EE00': {1300264: 'U1'} ,
'13G090C6ET013G0A0C6EI00': {1300264: 'U2'} ,
'13G080C6FH013G090C6ET00': {1300264: 'U3'} ,
'13FLF0C6GV013FLB0C6EB00': {1300265: 'U'} ,
'13FLB0C6EB013FJL0C6CP00': {1300265: 'NR'} ,
'13FJL0C6CP013FJ90C6CF00': {1300265: 'NR1'} ,
'13FJ90C6CF013FJ50C6CC00': {1300265: 'NR2'} ,
'13FMA0C6F1013FLB0C6EB00': {1300265: 'R'} ,
'13FML0C6F6013FMA0C6F100': {1300265: 'R1'} ,
'13FNK0C6G2013FML0C6F600': {1300265: 'R2'} ,
'13FJP0C6CM013FLB0C6EB00': {1300265: 'L'} ,
'13FLB0C6EB013FMJ0C6ES00': {1300265: 'NL'} ,
'13G2O0C6CL013G2N0C6D600': {1300357: 'U'} ,
'13G2N0C6D6013G2G0C6EB00': {1300357: 'U1'} ,
'13G2G0C6EB013G2F0C6EK00': {1300357: 'U2'} ,
'13G2F0C6EK013G2D0C6ER00': {1300357: 'U3'} ,
'13G600C6CK013G5B0C6CL00': {1300357: 'R3'} ,
'13G3J0C6CK013G600C6CK00': {1300357: 'NL2'} ,
'13FJ30C5VA013FJ50C5VJ00': {1300369: 'D'} ,
'13FJ10C5UQ013FJ30C5VA00': {1300369: 'D1'} ,
'13FJ50C5VJ013FJ30C5VA00': {1300369: 'NU'} ,
'13FKU0C60A013FK30C60A00': {1300373: 'R'} ,
'13FK30C60U013FK30C60A00': {1300373: 'U', 1300371: 'D'} ,
'13G2A0C5O5013G280C5O500': {1300063: 'R'} ,
'13FUD0C5K6013FUC0C5KS00': {1300116: 'D'} ,
'13FUC0C5JT013FUD0C5K600': {1300116: 'D1'} ,
'13FUC0C5KS013FUD0C5LK00': {1300116: 'ND'} ,
'13FUD0C5LK013FUD0C5MF00': {1300116: 'ND1'} ,
'13FUB0C5L9013FUC0C5KS00': {1300116: 'U'} ,
'13FUB0C5LE013FUB0C5L900': {1300116: 'U1'} ,
'13FUB0C5MH013FUB0C5LE00': {1300116: 'U2'} ,
'13FUC0C5KS013FUC0C5JT00': {1300116: 'NU'} ,
'13FHN0C64O013FH30C65500': {1300171: 'R'} ,
'13FGS0C65C013FH30C65500': {1300171: 'L', 1300172: 'NL'} ,
'13FH30C655013FGS0C65C00': {1300171: 'NR', 1300172: 'R'} ,
'13FH30C655013FHN0C64O00': {1300171: 'NL'} ,
'13FGS0C65C013FG90C65S00': {1300172: 'NR'} ,
'13FG90C65K013FGS0C65C00': {1300172: 'L'} ,
'13FHR0C65N013FGS0C65C00': {1300172: 'U'} ,
'13FK20C61T013FJ30C61O00': {1300250: 'R'} ,
'13FJ30C61O013FIC0C61K00': {1300250: 'L'} ,
'13FN70C5T5013FLC0C5T700': {1300242: 'R'} ,
'13FLC0C5T7013FL00C5T800': {1300242: 'NR'} ,
'13FL00C5T8013FLC0C5T700': {1300242: 'L'} ,
'13FLC0C5T7013FN70C5T500': {1300242: 'NL'} ,
'13FO10C6F3013FOH0C6F600': {2708375: 'L'} ,
'13FOH0C6F6013FPG0C6FC00': {2708375: 'R'} ,
'13FPG0C6FC013FQA0C6FA00': {2708375: 'R1'} ,
'13FQA0C6FA013FQO0C6FA00': {2708375: 'R2'} ,
'13FOR0C6F2013FOH0C6F600': {2708375: 'D'} ,
'13FJ00C5RV013FIT0C5RR00': {1300366: 'U'} ,
'13FK30C60U013FK20C61T00': {1300371: 'U'} ,
}
#
# path ="2025-08-22_online.txt"
#
# online_data = get_online_map(path)
# # print(online_data)
# state = get_Cross_id_online_state(online_data,1300194)
# print(state)