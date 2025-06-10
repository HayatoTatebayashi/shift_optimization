import json
import random
import datetime

# --- 設定パラメータ ---
NUM_FACILITIES = 48  # 実際に合わせる
NUM_EMPLOYEES = 350  # 実際に合わせる
PLANNING_START_DATE_STR = "2025-06-09"  # 計画開始日
NUM_DAYS_IN_PLANNING_PERIOD = 7      # 例: 1週間 (7, 14, 30など)
DAYS_OF_WEEK_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_CONSECUTIVE_WORK_DAYS_RANGE = (3, 6) # 連続勤務日数の上限（範囲）
TIME_LIMIT_SEC = 1800                     # ソルバーの計算時間制限
CLEANING_SHIFT_START_HOUR = 10
CLEANING_SHIFT_END_HOUR = 15

# 従業員関連の範囲設定
COST_PER_HOUR_RANGE = (1200.0, 1500.0)  # 時給（例: 円）
NUM_PREFERRED_FACILITIES_RANGE = (1, 7) # 従業員が希望する施設数の範囲
# AVAILABILITY_SLOTS_PER_DAY_RANGE = (0, 2) # 1日の勤務可能時間帯の数（0は非番）同日の重複申請
RANDOM_AVAILABILITY_START_HOUR_RANGE  = (8, 22)   # 勤務開始可能時間の範囲 (例: 6時～15時)
RANDOM_AVAILABILITY_DURATION_HOURS_RANGE = (5, 8) # 1つの勤務時間帯の長さの範囲
CONTRACT_MAX_DAYS_PER_WEEK_RANGE = (2, 5)   # 週の契約最大労働日数
CONTRACT_MAX_HOURS_PER_DAY_RANGE = (5, 8)    # 1日の契約最大労働時間

# 残業関連の範囲設定
TOTAL_OVERTIME_HOURS_RANGE = (0, 500) # 計画期間中の総残業時間の目標範囲
OVERTIME_COST_MULTIPLIER_RANGE = (1.25, 1.5) # 通常時給に対する残業時給の倍率
MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE = (0, 8) # 従業員1人あたりの最大残業時間（計画期間中）

# 清掃タスク関連の範囲設定
CLEANING_TASKS_PER_DAY_RANGE = (1, 158) # 1日あたりの清掃タスク数の範囲
DEFAULT_CLEANING_TASKS_PER_DAY_OF_WEEK_RANGE = (1, 158) # 曜日ごとのデフォルトタスク数

# 夜勤が翌日何時まで続くかのデフォルト (例: 9時 = 8時台まで勤務)
DEFAULT_NIGHT_SHIFT_CONTINUES_UNTIL_HOUR = 9
# 主要シフトを選ぶ確率 (例: 80%)
PROBABILITY_COMMON_SHIFT = 0.8
# 1日に複数のスロットをリクエストする確率 (主要シフトが選ばれた後、さらに追加する確率)
PROBABILITY_SECOND_SLOT = 0.1

# --- デフォルトペナルティ設定 ---
PENALTY_SETTINGS = {
    "consecutive_days_penalty": 50000, # 連続勤務日数のペナルティ
    "weekly_days_penalty": 40000, # 週勤務日数超過のペナルティ
    "daily_hours_penalty": 30000, # 1日勤務時間超過のペナルティ
    "staff_shortage_penalty": 100000 , # スタッフ不足のペナルティ
}
# 施設ごとのペナルティ調整の例 (スタッフ不足ペナルティの乗数)
FACILITY_STAFF_SHORTAGE_PENALTY_MULTIPLIER_RANGE = (0.5, 2.0) # デフォルトのペナルティに対する乗数

# --- アサイン難易度スコア計算用パラメータ ---
DIFFICULTY_SCORE_PARAMS = {
    "base_score_per_hour": 1, # 基本スコア（1時間あたり）
    "night_hour_multiplier": 1.5, # 夜勤時間帯のスコア倍率
    "weekend_day_multiplier": 1.3, # 週末のスコア倍率
    "global_difficulty_cost_multiplier": 0.1,  # グローバル難易度コスト倍率
    "fairness_penalty_weight_difficulty": 1000  # 公平性ペナルティの重み（難易度スコア計算用）
}
# 深夜とみなす時間帯 (0-23時表記)
NIGHT_HOURS_RANGE_FOR_DIFFICULTY = (22, 5) # 22時から翌朝5時 (5時台は含まない)


# --- 主要シフトパターン ---
COMMON_SHIFTS = [ # 不使用
    {"name": "Day", "start": 9, "end": 17},      # 9:00 - 17:00 (8h)
    {"name": "Evening", "start": 17, "end": 22}, # 17:00 - 22:00 (5h)
    {"name": "Evening", "start": 10, "end": 15}, # 10:00 - 15:00 (5h)
    {"name": "Night", "start": 22, "end": 33}    # 22:00 - 翌9:00 (11h), end は 24 + 9 で表現
]

DAY_SHIFTS = [
    {"name": "Day", "start": 9, "end": 17},
    {"name": "Evening", "start": 17, "end": 22},
    {"name": "Evening", "start": 10, "end": 15}
]
NIGHT_SHIFT = {"name": "Night", "start": 22, "end": 33}  # 22:00-9:00固定
NIGHT_SHIFT_PROBABILITY = 0.3  # 30%の確率で夜勤シフト


def format_time(hour):
    return f"{hour % 24:02d}:00"

# --- 入力データ生成関数 ---
def generate_schedule_data():
    # スケジュールデータの初期化
    schedule_data = {"settings": {}, "facilities": [], "employees": [], "overtime_lp": {}}
    schedule_data["settings"]["planning_start_date"] = PLANNING_START_DATE_STR
    schedule_data["settings"]["num_days_in_planning_period"] = NUM_DAYS_IN_PLANNING_PERIOD
    schedule_data["settings"]["days_of_week_order"] = DAYS_OF_WEEK_ORDER
    schedule_data["settings"]["max_consecutive_work_days"] = random.randint(*MAX_CONSECUTIVE_WORK_DAYS_RANGE)
    schedule_data["settings"]["hours_in_day"] = 24
    schedule_data["settings"]["cleaning_shift_start_hour"] = CLEANING_SHIFT_START_HOUR
    schedule_data["settings"]["cleaning_shift_end_hour"] = CLEANING_SHIFT_END_HOUR
    schedule_data["settings"].update(PENALTY_SETTINGS) # 定数辞書全体を挿入
    schedule_data["settings"].update(DIFFICULTY_SCORE_PARAMS)
    schedule_data["settings"]["NIGHT_HOURS_RANGE_FOR_DIFFICULTY"] = NIGHT_HOURS_RANGE_FOR_DIFFICULTY

    # 施設データの生成
    facility_ids = []
    for i in range(NUM_FACILITIES):
        facility_id = f"F{i+1:03d}"
        facility_ids.append(facility_id)
        
        # 施設ごとのカスタムペナルティ設定を追加
        facility_penalty_overrides = {}
        # 例: スタッフ不足ペナルティの乗数をランダムに設定
        if random.random() < 0.3: # 30%の確率でカスタム乗数を設定
            facility_penalty_overrides["staff_shortage_multiplier"] = \
                round(random.uniform(*FACILITY_STAFF_SHORTAGE_PENALTY_MULTIPLIER_RANGE), 2)
        # 他のソフト制約（例: 連続勤務のペナルティなど）も同様に追加可能だが現状の従業員単位の制約には不適用
        # facility_penalty_overrides["consecutive_days_penalty"] = new_value 
        # facility_penalty_overrides["daily_hours_multiplier"] = new_multiplier

        schedule_data["facilities"].append({
            "id": facility_id,
            "cleaning_capacity_tasks_per_hour_per_employee": random.randint(3, 8),
            "penalty_overrides": facility_penalty_overrides # ★追加
        })

    # 従業員データの生成
    employee_main_list_for_overtime = []
    for i in range(NUM_EMPLOYEES):
        emp_id = f"E{i+1:03d}"
        # cost_per_hour = round(random.uniform(*COST_PER_HOUR_RANGE), 2)
        num_prefs = random.randint(*NUM_PREFERRED_FACILITIES_RANGE)
        num_prefs = min(num_prefs, len(facility_ids))
        preferred_facilities = random.sample(facility_ids, num_prefs)

        # 勤務可能時間帯の生成
        availability = []
        num_preferred_work_days_this_week = random.randint(
            CONTRACT_MAX_DAYS_PER_WEEK_RANGE[0],
            CONTRACT_MAX_DAYS_PER_WEEK_RANGE[1]
        )
        preferred_work_days_indices = sorted(random.sample(range(len(DAYS_OF_WEEK_ORDER)), num_preferred_work_days_this_week))

        for day_idx, day_name in enumerate(DAYS_OF_WEEK_ORDER):
            if day_idx not in preferred_work_days_indices and random.random() > 0.1:
                continue

            current_day_slots_for_emp_tuples = [] # (start_hour, end_hour_abs) 重複チェック用
            num_slots_for_today = 1
            if random.random() < PROBABILITY_SECOND_SLOT:
                num_slots_for_today = 2

            for _ in range(num_slots_for_today):
                slot_to_add = None
                is_night_shift_flag = False

                # 夜勤シフトの確率を直接制御
                if random.random() < NIGHT_SHIFT_PROBABILITY:
                    # 夜勤シフトを生成
                    start_h_abs = NIGHT_SHIFT["start"]
                    end_h_abs = NIGHT_SHIFT["end"]
                    is_night_shift_flag = True
                    # 夜勤の場合は2つ目のスロットを生成しない
                    num_slots_for_today = 1
                else:
                    # 通常シフトを生成
                    chosen_shift = random.choice(DAY_SHIFTS)
                    start_h_abs = chosen_shift["start"]
                    end_h_abs = chosen_shift["end"]                
                
                # 時間を 0-23 の範囲に正規化しつつ、日付またぎを判定
                start_time_str = format_time(start_h_abs % 24)
                end_time_str = format_time(end_h_abs % 24)
                
                current_slot_tuple = (start_h_abs, end_h_abs)

                # 重複チェック
                is_overlapping = any(max(current_slot_tuple[0], s_tuple[0]) < min(current_slot_tuple[1], s_tuple[1]) 
                                     for s_tuple in current_day_slots_for_emp_tuples)

                if not is_overlapping and start_h_abs < end_h_abs : # start < end は絶対時間での比較
                    slot_info = {
                        "day_of_week": day_name,
                        "start_time": start_time_str,
                        "end_time": end_time_str
                    }
                    # is_night_shift フラグの判定: end_time が start_time より時刻として早い、または end_h_abs が24を超える場合
                    # (例: start 22:00, end 09:00  または start 22:00, end_abs 33)
                    if (int(end_time_str.split(':')[0]) < int(start_time_str.split(':')[0]) and end_h_abs > start_h_abs) or \
                       (end_h_abs > 23 and start_h_abs < 24) or \
                       is_night_shift_flag: # COMMON_SHIFTS からの指定も考慮
                        slot_info["is_night_shift"] = True
                    
                    availability.append(slot_info)
                    current_day_slots_for_emp_tuples.append(current_slot_tuple)

        if not availability: # フォールバック
            day_name = random.choice(DAYS_OF_WEEK_ORDER)
            chosen_shift = random.choice(COMMON_SHIFTS)
            start_h_abs, end_h_abs = chosen_shift["start"], chosen_shift["end"]
            
            slot_info = {
                "day_of_week": day_name,
                "start_time": format_time(start_h_abs % 24),
                "end_time": format_time(end_h_abs % 24)
            }
            if (int(slot_info["end_time"].split(':')[0]) < int(slot_info["start_time"].split(':')[0]) and end_h_abs > start_h_abs) or \
               (end_h_abs > 23 and start_h_abs < 24) or \
               chosen_shift["name"] == "Night":
                slot_info["is_night_shift"] = True
            availability.append(slot_info)
        
        employee_data = {
            "id": emp_id, "preferred_facilities": preferred_facilities,
            "availability": availability,
            "contract_max_days_per_week": random.randint(*CONTRACT_MAX_DAYS_PER_WEEK_RANGE),
            "contract_max_hours_per_day": random.randint(*CONTRACT_MAX_HOURS_PER_DAY_RANGE)
        }
        schedule_data["employees"].append(employee_data)
        # employee_main_list_for_overtime.append({"id": emp_id, "base_cost": cost_per_hour})

    # 残業LPデータの生成
    # schedule_data["overtime_lp"]["total_overtime_hours"] = random.randint(*TOTAL_OVERTIME_HOURS_RANGE)
    # overtime_employees = []
    # for emp_info in employee_main_list_for_overtime:
    #     overtime_cost = round(emp_info["base_cost"] * random.uniform(*OVERTIME_COST_MULTIPLIER_RANGE), 2)
    #     overtime_employees.append({
    #         "id": emp_info["id"], "overtime_cost": overtime_cost,
    #         "max_overtime": random.randint(*MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE)
    #     })
    # schedule_data["overtime_lp"]["employees"] = overtime_employees
    return schedule_data

# --- 清掃タスクデータ生成関数 ---
def generate_cleaning_tasks_data_for_input(settings_data, facilities_data):
    planning_start_date_str = settings_data["planning_start_date"]
    num_days_in_planning_period = settings_data["num_days_in_planning_period"]
    days_of_week_order = settings_data["days_of_week_order"]
    cleaning_tasks = {}
    start_date_obj = datetime.datetime.strptime(planning_start_date_str, "%Y-%m-%d").date()
    all_dates_in_period = [start_date_obj + datetime.timedelta(days=i) for i in range(num_days_in_planning_period)]
    for facility in facilities_data:
        facility_id = facility["id"]
        cleaning_tasks[facility_id] = {}
        tasks_by_day_of_week = {day: {} for day in days_of_week_order}
        for date_obj in all_dates_in_period:
            day_name = days_of_week_order[date_obj.weekday()]
            date_str = date_obj.strftime("%Y-%m-%d")
            tasks_by_day_of_week[day_name][date_str] = random.randint(*CLEANING_TASKS_PER_DAY_RANGE)
        for day_name_key, date_tasks_map in tasks_by_day_of_week.items():
            if date_tasks_map:
                 cleaning_tasks[facility_id][day_name_key] = date_tasks_map
        if random.choice([True, False]):
            cleaning_tasks[facility_id]["default_tasks_for_day_of_week"] = {}
            for day_name in days_of_week_order:
                cleaning_tasks[facility_id]["default_tasks_for_day_of_week"][day_name] = \
                    random.randint(*DEFAULT_CLEANING_TASKS_PER_DAY_OF_WEEK_RANGE)
    return cleaning_tasks

if __name__ == "__main__":
    schedule_part = generate_schedule_data()
    cleaning_part = generate_cleaning_tasks_data_for_input(
        schedule_part["settings"], 
        schedule_part["facilities"]
    )
    combined_data = {
        "schedule_input": schedule_part,
        "cleaning_tasks_input": cleaning_part
    }
    output_filename = "generated_combined_input_data.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=2, ensure_ascii=False)
    print(f"'{output_filename}' を生成しました。")