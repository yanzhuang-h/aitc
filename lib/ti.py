from datetime import datetime, timedelta
# #
# # current_time = int(time.time() * 1000)
# # t = time.localtime(current_time / 1000)
# #
# # minute = t.tm_min
# # shi=t.tm_hour
# # print(minute,shi)
# #
# # import random
# #
# # num = random.randint(0, 9)
# # print(num)
#
#
# import json
# import os
# from pathlib import Path
# BASE_DIR = Path(__file__).resolve().parent  # lib 目录
# info = BASE_DIR / "cross_info.json"
#
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# JIYAN_PATH = os.path.join(BASE_DIR, "beiyong1.json")
#
# with open(JIYAN_PATH, "r", encoding="utf-8") as f:
#     data_old = json.load(f)
#
# JIYAN_PATH1 = os.path.join(BASE_DIR, "wwx.json")
#
# with open(JIYAN_PATH1, "r", encoding="utf-8") as f:
#     data_new = json.load(f)
# road_ids = {
#     "1700067"
# # "1300044"
#
# }
# directions = {
#       "U",
#       "R",
#               # "L",
#               # "R",
#               }
#
# for road in data_new:
#     if road in road_ids:
#         for direction in data_new[road]:
#             if direction in directions:
#                 print(road, data_new[road])
#                 data_new[road][direction] = data_old[road][direction]
#                 print(road, data_new[road])
#
# WWX_PATH = os.path.join(BASE_DIR, "wwx.json")
#
# with open(WWX_PATH, "w", encoding="utf-8") as f:
#     json.dump(data_new, f, ensure_ascii=False, indent=4)
#
# print("已保存到:", WWX_PATH)

datas = [(datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')]
print(datas)