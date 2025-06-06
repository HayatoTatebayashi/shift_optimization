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
RANDOM_AVAILABILITY_START_HOUR_RANGE  = (8, 23)   # 勤務開始可能時間の範囲 (例: 6時～15時)
RANDOM_AVAILABILITY_DURATION_HOURS_RANGE = (5, 8) # 1つの勤務時間帯の長さの範囲
CONTRACT_MAX_DAYS_PER_WEEK_RANGE = (3, 5)   # 週の契約最大労働日数
CONTRACT_MAX_HOURS_PER_DAY_RANGE = (6, 10)    # 1日の契約最大労働時間

# 残業関連の範囲設定
TOTAL_OVERTIME_HOURS_RANGE = (0, 500) # 計画期間中の総残業時間の目標範囲
OVERTIME_COST_MULTIPLIER_RANGE = (1.25, 2.0) # 通常時給に対する残業時給の倍率
MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE = (0, 5) # 従業員1人あたりの最大残業時間（計画期間中）

# 清掃タスク関連の範囲設定
CLEANING_TASKS_PER_DAY_RANGE = (1, 158) # 1日あたりの清掃タスク数の範囲
DEFAULT_CLEANING_TASKS_PER_DAY_OF_WEEK_RANGE = (1, 158) # 曜日ごとのデフォルトタスク数

# ペナルティ設定 (solve_new.pyで使われるが、入力に含めておくことも可能)
PENALTY_SETTINGS = {
    "consecutive_days_penalty": 50000,
    "weekly_days_penalty": 40000,
    "daily_hours_penalty": 30000,
    "staff_shortage_penalty": 100000
}


# --- 主要シフトパターン ---
COMMON_SHIFTS = [
    {"name": "Day", "start": 9, "end": 17},      # 9:00 - 17:00 (8h)
    {"name": "Evening", "start": 17, "end": 22}, # 17:00 - 22:00 (5h)
    {"name": "Night", "start": 22, "end": 33}    # 22:00 - 翌9:00 (11h), end は 24 + 9 で表現
]
# 主要シフトを選ぶ確率 (例: 80%)
PROBABILITY_COMMON_SHIFT = 0.8
# 1日に複数のスロットをリクエストする確率 (主要シフトが選ばれた後、さらに追加する確率)
PROBABILITY_SECOND_SLOT = 0.1


def format_time(hour):
    return f"{hour % 24:02d}:00"

def generate_schedule_data():
    schedule_data = {"settings": {}, "facilities": [], "employees": [], "overtime_lp": {}}
    schedule_data["settings"]["planning_start_date"] = PLANNING_START_DATE_STR
    schedule_data["settings"]["num_days_in_planning_period"] = NUM_DAYS_IN_PLANNING_PERIOD
    schedule_data["settings"]["days_of_week_order"] = DAYS_OF_WEEK_ORDER
    schedule_data["settings"]["max_consecutive_work_days"] = random.randint(*MAX_CONSECUTIVE_WORK_DAYS_RANGE)
    schedule_data["settings"]["hours_in_day"] = 24
    schedule_data["settings"]["cleaning_shift_start_hour"] = CLEANING_SHIFT_START_HOUR
    schedule_data["settings"]["cleaning_shift_end_hour"] = CLEANING_SHIFT_END_HOUR
    schedule_data["settings"].update(PENALTY_SETTINGS)

    facility_ids = []
    for i in range(NUM_FACILITIES):
        facility_id = f"F{i+1:03d}"
        facility_ids.append(facility_id)
        schedule_data["facilities"].append({
            "id": facility_id,
            "cleaning_capacity_tasks_per_hour_per_employee": random.randint(3, 8)
        })

    employee_main_list_for_overtime = []
    for i in range(NUM_EMPLOYEES):
        emp_id = f"E{i+1:03d}"
        cost_per_hour = round(random.uniform(*COST_PER_HOUR_RANGE), 2)
        num_prefs = random.randint(*NUM_PREFERRED_FACILITIES_RANGE)
        num_prefs = min(num_prefs, len(facility_ids))
        preferred_facilities = random.sample(facility_ids, num_prefs)

        availability = []
        num_preferred_work_days_this_week = random.randint(
            CONTRACT_MAX_DAYS_PER_WEEK_RANGE[0], 
            CONTRACT_MAX_DAYS_PER_WEEK_RANGE[1]
        )
        preferred_work_days_indices = sorted(random.sample(range(len(DAYS_OF_WEEK_ORDER)), num_preferred_work_days_this_week))
        
        for day_idx, day_name in enumerate(DAYS_OF_WEEK_ORDER):
            if day_idx not in preferred_work_days_indices and random.random() > 0.1:
                continue

            current_day_slots_for_emp = [] 

            if random.random() < PROBABILITY_COMMON_SHIFT:
                chosen_shift = random.choice(COMMON_SHIFTS)
                start_h, end_h = chosen_shift["start"], chosen_shift["end"]
            else:
                start_h = random.randint(*RANDOM_AVAILABILITY_START_HOUR_RANGE) # 修正
                duration = random.randint(*RANDOM_AVAILABILITY_DURATION_HOURS_RANGE) # 修正
                end_h = start_h + duration
            
            if start_h < 24:
                actual_end_h_today = min(end_h, 24)
                if start_h < actual_end_h_today:
                    slot_today = (start_h, actual_end_h_today)
                    is_overlapping = any(max(slot_today[0], s[0]) < min(slot_today[1], s[1]) for s in current_day_slots_for_emp)
                    if not is_overlapping:
                        availability.append({
                            "day_of_week": day_name,
                            "start_time": format_time(start_h),
                            "end_time": format_time(actual_end_h_today)
                        })
                        current_day_slots_for_emp.append(slot_today)

            if end_h > 24:
                start_h_tomorrow = 0
                end_h_tomorrow = end_h % 24
                next_day_idx = (day_idx + 1) % len(DAYS_OF_WEEK_ORDER)
                next_day_name = DAYS_OF_WEEK_ORDER[next_day_idx]
                if start_h_tomorrow < end_h_tomorrow:
                    availability.append({
                        "day_of_week": next_day_name,
                        "start_time": format_time(start_h_tomorrow),
                        "end_time": format_time(end_h_tomorrow)
                    })

            if random.random() < PROBABILITY_SECOND_SLOT and len(current_day_slots_for_emp) < 2 :
                for _ in range(5): 
                    start_h2 = random.randint(*RANDOM_AVAILABILITY_START_HOUR_RANGE) # ★修正
                    duration2 = random.randint(*RANDOM_AVAILABILITY_DURATION_HOURS_RANGE) # ★修正
                    end_h2 = start_h2 + duration2
                    end_h2 = min(end_h2, 24)

                    if start_h2 < end_h2:
                        slot2 = (start_h2, end_h2)
                        is_overlapping = any(max(slot2[0], s[0]) < min(slot2[1], s[1]) for s in current_day_slots_for_emp)
                        if not is_overlapping:
                            availability.append({
                                "day_of_week": day_name,
                                "start_time": format_time(start_h2),
                                "end_time": format_time(end_h2)
                            })
                            current_day_slots_for_emp.append(slot2)
                            break

        if not availability:
            day_name = random.choice(DAYS_OF_WEEK_ORDER)
            chosen_shift = random.choice(COMMON_SHIFTS)
            start_h, end_h = chosen_shift["start"], chosen_shift["end"]
            if start_h < 24:
                availability.append({"day_of_week": day_name, "start_time": format_time(start_h), "end_time": format_time(min(end_h, 24))})
            if end_h > 24:
                next_day_idx = (DAYS_OF_WEEK_ORDER.index(day_name) + 1) % len(DAYS_OF_WEEK_ORDER)
                availability.append({"day_of_week": DAYS_OF_WEEK_ORDER[next_day_idx], "start_time": format_time(0), "end_time": format_time(end_h % 24)})

        employee_data = {
            "id": emp_id, "cost_per_hour": cost_per_hour, "preferred_facilities": preferred_facilities,
            "availability": availability,
            "contract_max_days_per_week": random.randint(*CONTRACT_MAX_DAYS_PER_WEEK_RANGE),
            "contract_max_hours_per_day": random.randint(*CONTRACT_MAX_HOURS_PER_DAY_RANGE)
        }
        schedule_data["employees"].append(employee_data)
        employee_main_list_for_overtime.append({"id": emp_id, "base_cost": cost_per_hour})

    schedule_data["overtime_lp"]["total_overtime_hours"] = random.randint(*TOTAL_OVERTIME_HOURS_RANGE)
    overtime_employees = []
    for emp_info in employee_main_list_for_overtime:
        overtime_cost = round(emp_info["base_cost"] * random.uniform(*OVERTIME_COST_MULTIPLIER_RANGE), 2)
        overtime_employees.append({
            "id": emp_info["id"], "overtime_cost": overtime_cost,
            "max_overtime": random.randint(*MAX_OVERTIME_HOURS_PER_EMPLOYEE_RANGE)
        })
    schedule_data["overtime_lp"]["employees"] = overtime_employees
    return schedule_data

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